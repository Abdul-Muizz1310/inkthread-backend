"""Documents and what the pipeline made of them; the admin's delete and reprocess (spec 07 § 2)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.core.errors import GraphNotReady, NotFound
from inkthread.domain.exports import cypher, graphml, jsonld
from inkthread.domain.model import Graph
from inkthread.domain.ops import Op
from inkthread.domain.why import Why, why
from inkthread.models import Document
from inkthread.repositories import documents, graphs, jobs
from inkthread.schemas.documents import DocumentOut, GeometryWord, UploadOut
from inkthread.schemas.jobs import JobOut
from inkthread.services.ingest import pdf_key
from inkthread.services.runner import page_geometry_key, page_png_key, pages_prefix
from inkthread.services.views import document_out, job_out
from inkthread.storage.blobs import BlobStore

ExportFormat = Literal["jsonld", "graphml", "cypher"]
_GEOMETRY: TypeAdapter[list[GeometryWord]] = TypeAdapter(list[GeometryWord])


@dataclass(frozen=True, slots=True)
class GraphPayload:
    """A stored graph, serialised, and its hash (the ETag)."""

    graph_hash: str
    body: bytes


@dataclass(frozen=True, slots=True)
class Export:
    """An export's bytes, media type and file name."""

    body: bytes
    media_type: str
    filename: str


_EXPORTS: dict[str, tuple[Callable[[Graph], bytes], str]] = {
    "jsonld": (jsonld.to_jsonld, "application/ld+json"),
    "graphml": (graphml.to_graphml, "application/graphml+xml"),
    "cypher": (cypher.to_cypher, "text/plain; charset=utf-8"),
}


class DocumentService:
    """Document reads, plus the admin's delete and reprocess."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        blobs: BlobStore,
        *,
        wake: Callable[[], None],
    ) -> None:
        self._sessions = sessions
        self._blobs = blobs
        self._wake = wake

    async def _doc(self, s: AsyncSession, document_id: uuid.UUID) -> Document:
        doc = await documents.get(s, document_id)
        if doc is None:
            raise NotFound(f"No document {document_id}.")
        return doc

    async def get(self, document_id: uuid.UUID) -> DocumentOut:
        """One document with its latest job and its graph's stats."""
        async with self._sessions() as s:
            doc = await self._doc(s, document_id)
            latest = await jobs.latest_for(s, doc.id)
            stats = await graphs.stats(s, doc.id)
            return document_out(doc, latest, stats)

    async def samples(self) -> list[DocumentOut]:
        """The curated samples, never uploads."""
        async with self._sessions() as s:
            out = []
            for doc in await documents.list_samples(s):
                latest = await jobs.latest_for(s, doc.id)
                out.append(document_out(doc, latest, await graphs.stats(s, doc.id)))
            return out

    async def job(self, job_id: uuid.UUID) -> JobOut:
        """One job."""
        async with self._sessions() as s:
            job = await jobs.get(s, job_id)
            if job is None:
                raise NotFound(f"No job {job_id}.")
            return job_out(job)

    async def _graph(self, document_id: uuid.UUID) -> tuple[Graph, list[Op]]:
        async with self._sessions() as s:
            await self._doc(s, document_id)
            row = await graphs.get(s, document_id)
        if row is None:
            raise GraphNotReady
        return Graph.model_validate(row.graph), [Op.model_validate(o) for o in row.ops]

    async def graph(self, document_id: uuid.UUID) -> GraphPayload:
        """The graph as stored, and its hash."""
        async with self._sessions() as s:
            await self._doc(s, document_id)
            row = await graphs.get(s, document_id)
        if row is None:
            raise GraphNotReady
        body = json.dumps(row.graph, ensure_ascii=False, separators=(",", ":")).encode()
        return GraphPayload(graph_hash=row.graph_hash, body=body)

    async def export(self, document_id: uuid.UUID, fmt: str) -> Export:
        """An export (spec 09); an unknown format is `NotFound`."""
        entry = _EXPORTS.get(fmt)
        if entry is None:
            raise NotFound(f"No export format {fmt!r}; use jsonld, graphml or cypher.")
        render, media = entry
        graph, _ = await self._graph(document_id)
        stem = (graph.document.sha256)[:12]
        return Export(body=render(graph), media_type=media, filename=f"inkthread-{stem}.{fmt}")

    async def why(self, document_id: uuid.UUID, element_id: str) -> Why:
        """Attribution for one node, edge or role (spec 06 § 6)."""
        graph, ops = await self._graph(document_id)
        try:
            return why(graph, ops, element_id)
        except KeyError:
            raise NotFound(f"No element {element_id!r} in this graph.") from None

    async def _page_blob(
        self, document_id: uuid.UUID, page: int, key: Callable[[str, int], str]
    ) -> bytes:
        async with self._sessions() as s:
            doc = await self._doc(s, document_id)
        if not 1 <= page <= doc.page_count:
            raise NotFound(f"No page {page}; the document has {doc.page_count}.")
        data = await self._blobs.get(key(doc.sha256, page))
        if data is None:
            raise NotFound(f"Page {page} is not rendered yet.")
        return data

    async def page_png(self, document_id: uuid.UUID, page: int) -> bytes:
        """A rendered page."""
        return await self._page_blob(document_id, page, page_png_key)

    async def page_geometry(self, document_id: uuid.UUID, page: int) -> list[GeometryWord]:
        """A page's word geometry, parsed (spec 02 § 9)."""
        return _GEOMETRY.validate_json(await self._page_blob(document_id, page, page_geometry_key))

    async def delete(self, document_id: uuid.UUID) -> None:
        """Delete a document, its rows (by cascade) and its blobs."""
        async with self._sessions() as s, s.begin():
            doc = await self._doc(s, document_id)
            sha = doc.sha256
            await documents.delete(s, doc.id)
        await self._blobs.delete_prefix(pdf_key(sha))
        await self._blobs.delete_prefix(pages_prefix(sha))

    async def reprocess(self, document_id: uuid.UUID) -> UploadOut:
        """Queue the pipeline again (an active job is returned as is)."""
        async with self._sessions() as s, s.begin():
            doc = await self._doc(s, document_id)
            job = await jobs.active_for(s, doc.id)
            if job is None:
                job = await jobs.create(s, doc.id)
                doc.status = "queued"
                await s.flush()
            out = UploadOut(
                document=document_out(doc, job, await graphs.stats(s, doc.id)), job=job_out(job)
            )
        self._wake()
        return out
