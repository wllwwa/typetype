"""52dazi 数据传输对象。"""

from dataclasses import dataclass
from enum import IntEnum


class DaziCompetitionType(IntEnum):
    """52dazi 竞赛类型编号。"""

    JISU = 0
    JINBIAO = 2
    JIANSHEN = 4

    @property
    def label(self) -> str:
        return {
            DaziCompetitionType.JISU: "极速杯",
            DaziCompetitionType.JINBIAO: "锦标赛",
            DaziCompetitionType.JIANSHEN: "键神杯",
        }[self]

    @property
    def segment_identity(self) -> int:
        """官网成绩文本使用的竞赛段号。"""
        # 与 52dazi 网页 getCompetitionText 的当前映射保持一致。
        return {
            DaziCompetitionType.JISU: 99999,
            DaziCompetitionType.JINBIAO: 100000,
            DaziCompetitionType.JIANSHEN: 99999,
        }[self]

    @classmethod
    def from_code(cls, code: int) -> "DaziCompetitionType":
        try:
            return cls(int(code))
        except (TypeError, ValueError):
            return cls.JISU


@dataclass(frozen=True)
class DaziLoginResult:
    """登录接口返回的会话信息。"""

    token: str
    cookie: str = ""
    display_name: str = ""


@dataclass(frozen=True)
class DaziCompetitionText:
    """52dazi 竞赛文本。"""

    content: str
    title: str
    author: str
    word_num: int
    competition_type: DaziCompetitionType


@dataclass(frozen=True)
class DaziUploadOutcome:
    """成绩上传结果。"""

    message: str
    ranking: str = ""
