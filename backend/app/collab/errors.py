"""协作域统一错误类型。

错误信息只描述调用方自己空间内的事实：
- 跨空间访问一律按"不存在"处理，不能在消息里暴露另一个空间的实体名称或字段；
- 未认证、非成员、只读越权各自有独立状态码，便于服务端审计与前端区分。
"""
from __future__ import annotations


class CollabError(Exception):
    """协作域业务错误基类，默认按 400 处理。"""

    status_code = 400

    def __init__(self, message: str, *, status_code: int | None = None, details: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        # 机器可读的冲突/裁决细节，只包含调用方本空间的数据
        self.details = details


class AuthError(CollabError):
    """缺少或无法识别本地身份（请求头里的用户不存在）。"""

    status_code = 401


class ForbiddenError(CollabError):
    """身份有效，但在目标空间无成员资格或角色不允许该操作。"""

    status_code = 403


class NotFoundError(CollabError):
    """实体不存在，或实体属于别的空间——对外表现完全一致，杜绝归属探测。"""

    status_code = 404


class ConflictError(CollabError):
    """并发编辑冲突，调用方需要重新拉取草稿后再决定如何合并。"""

    status_code = 409


class ValidationError(CollabError):
    """调用方输入不合法（字段、标识、范围等），状态码保持 400。"""

    status_code = 400


class TransactionError(CollabError):
    """事务内任一步骤失败，整体回滚后对外报告的错误。"""

    status_code = 500
