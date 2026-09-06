"""
Offline unit tests: mock XML-RPC transports simulating the behaviors of
different Typecho server generations:

- < 1.2      wp.newCategory returns the new mid as str
- 1.2.0      wp.newCategory is broken server-side (HTTP 500 -> ProtocolError)
- >= 1.2.1   wp.newCategory returns int, but duplicate names raise Fault 404
"""
import unittest
import xmlrpc.client
from dataclasses import asdict, is_dataclass

from pytypecho import Typecho, AsyncTypecho, Post, Category

URL = "http://example.invalid/index.php/action/xmlrpc"
EXISTING = {"categoryId": 7, "parentId": 0, "categoryName": "News"}


def marshal(args):
    """Mirror what a real XML-RPC transport does to dataclass params."""
    return tuple(
        asdict(a) if is_dataclass(a) and not isinstance(a, type) else a
        for a in args
    )


def legacy_server(method, args):
    """Typecho < 1.2: str mid, descriptive errors."""
    if method == "wp.newCategory":
        return "7"
    if method == "metaWeblog.getCategories":
        return [dict(EXISTING, categoryId="7")]
    raise AssertionError(method)


def modern_server(method, args):
    """Typecho >= 1.2.1 / 1.3: int mid, duplicate name masked as fault 404.

    Args follow the wire protocol: (blogId, userName, password, ...rest).
    """
    if method == "wp.newCategory":
        name = args[3]["name"]
        if name == EXISTING["categoryName"]:
            raise xmlrpc.client.Fault(404, "分类不存在")
        return 9
    if method == "metaWeblog.getCategories":
        return [dict(EXISTING)]
    if method == "metaWeblog.newPost":
        return 99
    raise AssertionError(method)


def broken_120_server(method, args):
    """Typecho 1.2.0: every wp.newCategory dies with HTTP 500."""
    if method == "wp.newCategory":
        raise xmlrpc.client.ProtocolError(URL, 500, "Internal Server Error", {})
    if method == "metaWeblog.getCategories":
        return []
    raise AssertionError(method)


def post_recorder_server(record):
    """Echo server that records metaWeblog.newPost structs and returns 99."""

    def dispatch(method, args):
        if method == "metaWeblog.newPost":
            record.append((args[3], args[4]))
            return 99
        raise AssertionError(method)

    return dispatch


class _FakeNode:
    def __init__(self, fake, path):
        self._fake = fake
        self._path = path

    def __getattr__(self, name):
        return _FakeNode(self._fake, [*self._path, name])

    def __call__(self, *args):
        return self._fake._call(".".join(self._path), args)


class FakeProxy(_FakeNode):
    """Sync stand-in for xmlrpc.client.ServerProxy."""

    def __init__(self, dispatch):
        super().__init__(self, [])
        self.dispatch = dispatch
        self.calls = []

    def _call(self, path, args):
        args = marshal(args)
        self.calls.append((path, args))
        return self.dispatch(path, args)


class _FakeAsyncNode:
    def __init__(self, fake, path):
        self._fake = fake
        self._path = path

    def __getattr__(self, name):
        return _FakeAsyncNode(self._fake, [*self._path, name])

    async def __call__(self, *args):
        return self._fake._call(".".join(self._path), args)


class FakeAsyncProxy(_FakeAsyncNode):
    """Async stand-in for pytypecho.aio.AsyncServerProxy."""

    def __init__(self, dispatch):
        super().__init__(self, [])
        self.dispatch = dispatch
        self.calls = []

    def _call(self, path, args):
        args = marshal(args)
        self.calls.append((path, args))
        return self.dispatch(path, args)


def make_sync_client(dispatch):
    te = Typecho(URL, "user", "password")
    te.s = FakeProxy(dispatch)
    return te


def make_async_client(dispatch):
    te = AsyncTypecho(URL, "user", "password")
    te.s = FakeAsyncProxy(dispatch)
    return te


class SyncNewCategoryTestCase(unittest.TestCase):
    def test_modern_returns_int(self):
        te = make_sync_client(modern_server)
        r = te.new_category(Category(name="Tech"))
        self.assertIs(type(r), int)
        self.assertEqual(r, 9)

    def test_legacy_str_mid_normalized(self):
        te = make_sync_client(legacy_server)
        r = te.new_category(Category(name="News"))
        self.assertIs(type(r), int)
        self.assertEqual(r, 7)

    def test_duplicate_falls_back_to_existing(self):
        te = make_sync_client(modern_server)
        r = te.new_category(Category(name="News"))
        self.assertEqual(r, 7)

    def test_legacy_duplicate_falls_back_to_existing(self):
        def server(method, args):
            if method == "wp.newCategory":
                raise xmlrpc.client.Fault(403, "分类名称已经存在")
            if method == "metaWeblog.getCategories":
                return [dict(EXISTING, categoryId="7")]
            raise AssertionError(method)

        te = make_sync_client(server)
        self.assertEqual(te.new_category(Category(name="News")), 7)

    def test_broken_120_returns_none(self):
        te = make_sync_client(broken_120_server)
        self.assertIsNone(te.new_category(Category(name="Anything")))

    def test_unknown_category_without_server_returns_none(self):
        def server(method, args):
            if method == "wp.newCategory":
                raise xmlrpc.client.Fault(404, "分类不存在")
            if method == "metaWeblog.getCategories":
                return [dict(EXISTING, categoryName="Other")]
            raise AssertionError(method)

        te = make_sync_client(server)
        self.assertIsNone(te.new_category(Category(name="Never Heard")))


class AsyncNewCategoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_modern_returns_int(self):
        te = make_async_client(modern_server)
        r = await te.new_category(Category(name="Tech"))
        self.assertIs(type(r), int)
        self.assertEqual(r, 9)

    async def test_legacy_str_mid_normalized(self):
        te = make_async_client(legacy_server)
        r = await te.new_category(Category(name="News"))
        self.assertEqual(r, 7)

    async def test_duplicate_falls_back_to_existing(self):
        te = make_async_client(modern_server)
        self.assertEqual(await te.new_category(Category(name="News")), 7)

    async def test_broken_120_returns_none(self):
        te = make_async_client(broken_120_server)
        self.assertIsNone(await te.new_category(Category(name="Anything")))


class SyncPostStructTestCase(unittest.TestCase):
    def test_empty_post_status_stripped(self):
        record = []
        te = make_sync_client(post_recorder_server(record))
        te.new_post(Post(title="T", description="D"), publish=False)
        method, args = te.s.calls[-1]
        self.assertEqual(method, "metaWeblog.newPost")
        struct, publish = record[-1]
        self.assertNotIn("post_status", struct)
        self.assertFalse(publish)

    def test_explicit_post_status_kept(self):
        record = []
        te = make_sync_client(post_recorder_server(record))
        te.new_post(Post(title="T", description="D", post_status="draft"), publish=True)
        struct, publish = record[-1]
        self.assertEqual(struct["post_status"], "draft")
        self.assertTrue(publish)

    def test_edit_post_injects_post_id(self):
        record = []
        te = make_sync_client(post_recorder_server(record))
        te.edit_post(Post(title="T", description="D"), post_id=42, publish=True)
        struct, _ = record[-1]
        self.assertEqual(struct["postId"], 42)
        self.assertNotIn("post_status", struct)

    def test_page_struct_no_post_status(self):
        from pytypecho import Page

        record = []
        te = make_sync_client(post_recorder_server(record))
        te.new_page(Page(title="T", description="D"), publish=False)
        struct, _ = record[-1]
        self.assertEqual(struct["post_type"], "page")
        self.assertNotIn("post_status", struct)

    def test_page_status_sent_as_page_status(self):
        # Typecho reads page state from the 'page_status' struct key
        from pytypecho import Page

        record = []
        te = make_sync_client(post_recorder_server(record))
        te.new_page(Page(title="T", description="D", post_status="draft"), publish=True)
        struct, _ = record[-1]
        self.assertEqual(struct["page_status"], "draft")
        self.assertNotIn("post_status", struct)

    def test_date_created_defaults_to_now_per_instance(self):
        import time

        first = Post(title="A", description="D")
        time.sleep(0.01)
        second = Post(title="B", description="D")
        self.assertLess(first.dateCreated, second.dateCreated)


class AttachmentMarshalingTestCase(unittest.TestCase):
    def test_new_attachment_sends_binary(self):
        import io
        import xmlrpc.client as xclient

        from pytypecho import Attachment

        captured = []

        class Node:
            def __getattr__(self, name):
                return self

            def __call__(self, *args):
                captured.append(args)
                return {"id": 3}

        te = Typecho(URL, "user", "password")
        te.s = Node()
        te.new_attachment(Attachment(name="pic.png", bytes=io.BytesIO(b"png")))
        blog_id, user, password, data = captured[0]
        self.assertEqual(data["name"], "pic.png")
        self.assertIsInstance(data["bytes"], xclient.Binary)
        self.assertEqual(data["bytes"].data, b"png")


class AsyncPostStructTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_empty_post_status_stripped(self):
        record = []
        te = make_async_client(post_recorder_server(record))
        await te.new_post(Post(title="T", description="D"), publish=False)
        struct, publish = record[-1]
        self.assertNotIn("post_status", struct)
        self.assertFalse(publish)

    async def test_explicit_post_status_kept(self):
        record = []
        te = make_async_client(post_recorder_server(record))
        await te.new_post(
            Post(title="T", description="D", post_status="private"), publish=True
        )
        struct, _ = record[-1]
        self.assertEqual(struct["post_status"], "private")


if __name__ == "__main__":
    unittest.main()
