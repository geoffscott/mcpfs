"""Smoke-test that tools register with the expected annotations and output schemas.

This avoids any network or GCS dependency by substituting the backend with a
minimal fake.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mcpfs.gcs import ListEntry, ListPage, ObjectStat
from mcpfs.server import _build_mcp


@dataclass
class FakeBackend:
    def stat(self, name: str) -> ObjectStat:  # pragma: no cover - unused in this suite
        raise NotImplementedError

    def read(self, name: str):  # pragma: no cover - unused
        raise NotImplementedError

    def write(self, *a, **kw):  # pragma: no cover - unused
        raise NotImplementedError

    def delete(self, *a, **kw):  # pragma: no cover - unused
        raise NotImplementedError

    def list(self, prefix, recursive, page_size=None, cursor=None):
        return ListPage(
            entries=[
                ListEntry(
                    name="hello.txt",
                    kind="file",
                    size=5,
                    updated="2024-01-01T00:00:00+00:00",
                )
            ],
            next_cursor=None,
        )


_RO = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_RW = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}
EXPECTED = {
    "fs_list": _RO,
    "fs_stat": _RO,
    "fs_read": _RO,
    "fs_write": _RW,
    "fs_delete": _RW,
}


@pytest.fixture
def mcp():
    return _build_mcp(FakeBackend())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_all_tools_registered(mcp):
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == set(EXPECTED.keys())


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,expected", list(EXPECTED.items()))
async def test_tool_annotations(mcp, tool_name, expected):
    tool = next(t for t in await mcp.list_tools() if t.name == tool_name)
    ann = tool.annotations
    assert ann is not None, f"{tool_name} missing annotations"
    for field, value in expected.items():
        assert getattr(ann, field) == value, f"{tool_name}.{field}"


@pytest.mark.asyncio
async def test_output_schemas_present(mcp):
    tools = await mcp.list_tools()
    for t in tools:
        assert t.outputSchema is not None, f"{t.name} missing outputSchema"


@pytest.mark.asyncio
async def test_fs_list_input_schema_includes_pagination(mcp):
    tool = next(t for t in await mcp.list_tools() if t.name == "fs_list")
    props = tool.inputSchema.get("properties", {})
    assert "cursor" in props
    assert "page_size" in props
