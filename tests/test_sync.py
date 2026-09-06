import os
import unittest
import uuid

from pytypecho import Typecho, Post, Page, Category, Comment, Attachment


class TypechoTestCase(unittest.TestCase):
    def setUp(self):
        if not os.environ.get("XMLRPC_URL"):
            self.skipTest("XMLRPC_URL not set; live tests skipped")
        self.te = Typecho(
            rpc_url=os.environ.get("XMLRPC_URL"),
            username=os.environ.get("XMLRPC_USER_NAME"),
            password=os.environ.get("XMLRPC_USER_PASSWORD"),
            debug=os.environ.get("TEST_DEBUG", False),
        )


class TypechoPostTestCase(TypechoTestCase):
    def test_get_post(self):
        r = self.te.get_post(1)
        self.assertIsNotNone(r)

    def test_get_posts(self):
        r = self.te.get_posts()
        self.assertIsNotNone(r)

    def test_new_post(self):
        post = Post(title="Post Title", description="Post Description")
        r = self.te.new_post(post, publish=True)
        self.assertIsNotNone(r)
        self.assertIs(type(r), int)

    def test_edit_post(self):
        post = Post(title="Post Title", description="Post Description")
        num = self.te.new_post(post, publish=True)
        post_edited = Post(
            title="Edited Post Title", description="Edited Post Description"
        )
        r = self.te.edit_post(post_edited, post_id=int(num), publish=True)
        self.assertIsNotNone(r)
        self.assertEqual(r, num)

    def test_del_post(self):
        post = Post(title="Del Post Title", description="Del Post Description")
        num = self.te.new_post(post, publish=True)
        r = self.te.del_post(int(num))
        self.assertIsNotNone(r)

    def test_new_post_draft(self):
        title = "Draft Post Title %s" % uuid.uuid4().hex[:8]
        num = self.te.new_post(Post(title=title, description="D"), publish=False)
        self.assertIs(type(num), int)
        posts = self.te.get_posts(30) or []
        draft = next((p for p in posts if p.get("title") == title), None)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.get("post_status"), "draft")
        self.te.del_post(int(num))


class TypechoPageTestCase(TypechoTestCase):
    def test_get_page(self):
        r = self.te.get_page(2)
        self.assertIsNotNone(r)

    def test_get_pages(self):
        r = self.te.get_pages()
        self.assertIsNotNone(r)

    def test_new_page(self):
        page = Page(title="Page Title", description="Page Description")
        r = self.te.new_page(page, publish=True)
        self.assertIsNotNone(r)
        self.assertIs(type(r), int)

    def test_edit_page(self):
        page = Page(title="Page Title", description="Page Description")
        num = self.te.new_page(page, publish=True)
        page_edited = Page(
            title="Edited Page Title", description="Edited Page Description"
        )
        r = self.te.edit_page(page_edited, page_id=int(num), publish=True)
        self.assertIsNotNone(r)
        self.assertEqual(r, num)

    def test_del_post(self):
        page = Page(title="Del Page Title", description="Del Page Description")
        num = self.te.new_page(page, publish=True)
        r = self.te.del_page(int(num))
        self.assertIsNotNone(r)


class TypechoCategoryTestCase(TypechoTestCase):
    def test_get_category(self):
        r = self.te.get_categories()
        self.assertIsNotNone(r)
        self.assertEqual(r[0]["categoryName"], "默认分类")

    def test_new_category(self):
        name = "New Category %s" % uuid.uuid4().hex[:8]
        r = self.te.new_category(Category(name=name))
        self.assertIs(type(r), int)
        names = {c["categoryName"] for c in (self.te.get_categories() or [])}
        self.assertIn(name, names)
        self.te.del_category(r)

    def test_new_category_duplicate(self):
        # On Typecho >= 1.2.1 duplicates raise an opaque fault 404; the client
        # falls back to the existing category (get-or-create).
        name = "Dup Category %s" % uuid.uuid4().hex[:8]
        first = self.te.new_category(Category(name=name))
        second = self.te.new_category(Category(name=name))
        self.assertIs(type(first), int)
        self.assertEqual(first, second)
        self.te.del_category(first)

    def test_del_category(self):
        name = "Del Category %s" % uuid.uuid4().hex[:8]
        r = self.te.new_category(Category(name=name))
        self.assertIsNotNone(self.te.del_category(r))


class TypechoTagTestCase(TypechoTestCase):
    def test_get_tags(self):
        r = self.te.get_tags()
        self.assertCountEqual(r, [])


class TypechoCommentTestCase(TypechoTestCase):
    def test_get_comment(self):
        r = self.te.get_comment(1)
        self.assertIsNotNone(r)
        self.assertEqual(r["author"], "Typecho")

    def test_get_comments(self):
        r = self.te.get_comments()
        self.assertIsNotNone(r)
        self.assertEqual(r[0]["content"], "欢迎加入 Typecho 大家族")


class TypechoAttachementTestCase(TypechoTestCase):
    def test_get_attachments(self):
        r = self.te.get_attachments()
        self.assertCountEqual(r, [])
