from xmlrpc.client import Binary, ServerProxy, Fault
from typing import Any, List, Dict, Optional
from dataclasses import asdict

from .log import logger
from .models import Post, Page, Category, Attachment, Comment
from .aio import AsyncServerProxy


def _to_int(value: Any) -> Optional[int]:
    """
    Typecho returns the new id as int (>= 1.2.1) or str (< 1.2), normalize it.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_category_id(categories: Any, name: str) -> Optional[int]:
    for cat in categories or ():
        if isinstance(cat, dict) and cat.get("categoryName") == name:
            category_id = _to_int(cat.get("categoryId"))
            if category_id is not None:
                return category_id
    return None


def _resolve_existing_category(categories: Any, name: str) -> Optional[int]:
    existing = _find_category_id(categories, name)
    if existing is not None:
        logger.warning(
            "Category '%s' was not created (already exists?), "
            "returning existing id %s",
            name,
            existing,
        )
    else:
        logger.error(
            "Failed to create category '%s'. If your server is Typecho 1.2.0, "
            "wp.newCategory is broken server-side (upgrade to >= 1.2.1, see "
            "typecho PR #1443); otherwise check the name/slug for conflicts.",
            name,
        )
    return existing


def _content_struct(content: Any, **extra: Any) -> dict:
    """
    Drop an empty post_status: Typecho maps it back to 'publish', which would
    override publish=False. An explicit post_status still wins over publish.
    """
    d = asdict(content)
    if d.get("post_status") == "":
        del d["post_status"]
    d.update(extra)
    return d


def _page_struct(page: Any, **extra: Any) -> dict:
    """
    Pages read their status from the 'page_status' key server-side; the
    dataclass only has post_status, so rename it.
    """
    d = _content_struct(page, **extra)
    if d.get("post_status"):
        d["page_status"] = d.pop("post_status")
    return d


class TypechoPostMixin:
    def get_posts(self, num: int = 10) -> Optional[List[Dict]]:
        return self.try_rpc(self.s.metaWeblog.getRecentPosts, num)

    def get_post(self, post_id: int) -> Optional[Dict]:
        return self._try_rpc(
            self.s.metaWeblog.getPost, post_id, self.username, self.password
        )

    def new_post(self, post: Post, publish: bool) -> Optional[int]:
        """
        An explicit post_status ('draft'/'pending'/'private') takes precedence
        over publish. Missing categories are created automatically by Typecho.
        Returns the new post id, or None on failure.
        """
        return self.try_rpc(self.s.metaWeblog.newPost, _content_struct(post), publish)

    def edit_post(self, post: Post, post_id: int, publish: bool) -> Optional[int]:
        return self.try_rpc(
            self.s.metaWeblog.newPost, _content_struct(post, postId=post_id), publish
        )

    def del_post(self, post_id: int) -> Optional[bool]:
        return self._try_rpc(
            self.s.blogger.deletePost,
            self.blog_id,
            post_id,
            self.username,
            self.password,
            True,
        )


class TypechoPageMixin:
    def get_pages(self) -> Optional[List[Dict]]:
        return self.try_rpc(self.s.wp.getPages)

    def get_page(self, page_id: int) -> Optional[Dict]:
        """
        WARNING: Different from other API!
        """
        return self._try_rpc(
            self.s.wp.getPage, self.blog_id, page_id, self.username, self.password
        )

    def new_page(self, page: Page, publish: bool) -> Optional[int]:
        """
        An explicit page status ('draft'/'private') takes precedence over
        publish. Returns the new page id, or None on failure.
        """
        return self.try_rpc(self.s.metaWeblog.newPost, _page_struct(page), publish)

    def edit_page(self, page: Page, page_id: int, publish: bool) -> Optional[int]:
        return self.try_rpc(
            self.s.metaWeblog.newPost, _page_struct(page, postId=page_id), publish
        )

    def del_page(self, page_id: int) -> Optional[bool]:
        return self.try_rpc(self.s.wp.deletePage, page_id)


class TypechoCategoryMixin:
    def get_categories(self) -> Optional[List[Dict]]:
        return self.try_rpc(self.s.metaWeblog.getCategories)

    def new_category(self, category: Category) -> Optional[int]:
        """
        Create a category and return its id (int, on every Typecho version).

        Typecho < 1.2 returns the id as str, >= 1.2.1 as int; both are
        normalized here. If creation is rejected (Typecho >= 1.2.1 reports
        duplicate names etc. as an opaque fault 404), fall back to returning
        the id of an existing category with the same name (get-or-create).
        """
        category_id = _to_int(self.try_rpc(self.s.wp.newCategory, category))
        if category_id is not None:
            return category_id

        return _resolve_existing_category(
            self.try_rpc(self.s.metaWeblog.getCategories), category.name
        )

    def del_category(self, category_id: int) -> Optional[bool]:
        return self.try_rpc(self.s.wp.deleteCategory, category_id)


class TypechoTagMixin:
    def get_tags(self) -> Optional[List[Dict]]:
        return self.try_rpc(self.s.wp.getTags)


class TypechoAttachmentMixin:
    def get_attachments(
        self,
        post_id: int = None,
        mime_type: str = None,
        page_size: int = None,
        page_num: int = None,
    ) -> Optional[List[Dict]]:
        struct = {}
        if post_id:
            struct.update({"parent_id": post_id})
        if mime_type:
            struct.update({"mime_type": mime_type})
        if page_size:
            struct.update({"number": page_size})
        if page_num:
            struct.update({"offset": page_num})
        return self.try_rpc(self.s.wp.getMediaLibrary, struct)

    def get_attachment(self, attachment_id) -> Optional[Dict]:
        return self.try_rpc(self.s.wp.getMediaItem, attachment_id)

    def new_attachment(self, data: Attachment) -> Optional[Dict]:
        # built by hand: asdict() deep-copies, which cannot pickle the open
        # file object, and a raw file object does not survive marshaling
        payload = {"name": data.name, "bytes": Binary(data.bytes.read())}
        return self.try_rpc(self.s.wp.uploadFile, payload)


class TypechoCommentMixin:
    def get_comments(
        self,
        status: str = None,
        post_id: int = None,
        page_size: int = None,
        page_num: int = None,
    ) -> Optional[List[Dict]]:
        struct = {}
        if status:
            struct.update({"status": status})
        if post_id:
            struct.update({"parent_id": post_id})
        if page_size:
            struct.update({"number": page_size})
        if page_num:
            struct.update({"offset": page_num})
        return self.try_rpc(self.s.wp.getComments, struct)

    def get_comment(self, comment_id: int) -> Optional[Dict]:
        return self.try_rpc(self.s.wp.getComment, comment_id)

    def new_comment(
        self, comment: Comment, post_id: int, comment_parent: str = None
    ) -> Optional[int]:
        d = asdict(comment)
        if comment_parent:
            d.update({"comment_parent": comment_parent})
        path = post_id
        return self.try_rpc(self.s.wp.newComment, path, d)

    def edit_comment(self, comment: Comment, comment_id: int) -> Optional[bool]:
        return self.try_rpc(self.s.wp.editComment, comment_id, comment)

    def del_comment(self, comment_id: int) -> Optional[bool]:
        return self.try_rpc(
            self.s.wp.deleteComment,
            comment_id,
        )


class Typecho(
    TypechoPostMixin,
    TypechoPageMixin,
    TypechoCategoryMixin,
    TypechoTagMixin,
    TypechoAttachmentMixin,
    TypechoCommentMixin,
):
    def __init__(self, rpc_url: str, username: str, password: str, debug: bool = False):
        self.rpc_url = rpc_url
        self.username = username
        self.password = password

        self.s = ServerProxy(rpc_url, verbose=debug)
        # blog id could be any number.
        self.blog_id = 1

    def try_rpc(self, rpc_method, *args, **kw):
        return self._try_rpc(
            rpc_method, self.blog_id, self.username, self.password, *args, **kw
        )

    def _try_rpc(self, rpc_method, *args, **kw):
        res = None
        try:
            res = rpc_method(*args, **kw)
            logger.info(res)
            if res == "":
                res = None
        except Fault as e:
            logger.error("Error {}: {}".format(e.faultCode, e.faultString))
        except Exception as e:
            logger.error("Error {}".format(e))
        return res


class AsyncTypecho(Typecho):
    def __init__(self, rpc_url: str, username: str, password: str, semaphore=4):
        self.rpc_url = rpc_url
        self.username = username
        self.password = password

        self.s = AsyncServerProxy(rpc_url, semaphore)
        # blog id could be any number.
        self.blog_id = 1

    async def try_rpc(self, rpc_method, *args, **kw):
        return await self._try_rpc(
            rpc_method, self.blog_id, self.username, self.password, *args, **kw
        )

    async def _try_rpc(self, rpc_method, *args, **kw):
        res = None
        try:
            res = await rpc_method(*args, **kw)
            logger.info(res)
            if res == "":
                res = None
        except Fault as e:
            logger.error("Error {}: {}".format(e.faultCode, e.faultString))
        except Exception as e:
            logger.error("Error {}".format(e))
        return res

    async def new_category(self, category: Category) -> Optional[int]:
        """Async counterpart of TypechoCategoryMixin.new_category."""
        category_id = _to_int(await self.try_rpc(self.s.wp.newCategory, category))
        if category_id is not None:
            return category_id

        return _resolve_existing_category(
            await self.try_rpc(self.s.metaWeblog.getCategories), category.name
        )
