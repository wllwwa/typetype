# 52dazi 成绩上传接入交接

> 更新时间：2026-08-30
> 状态：协议、业务、适配层测试和代码审查已完成；真实网关验证仍需测试账号。

## 目标

让 `typetype` 能够登录 52dazi，载入以下竞赛赛文并在完成后由用户显式上传成绩：

| 比赛 | `competitionType` |
| --- | ---: |
| 极速杯 | `0` |
| 锦标赛 | `2` |
| 键神杯 | `4` |

协议调查来源：仓库根目录的 [只读调查报告.md](../../只读调查报告.md)。52dazi 实际网关为 `https://www.jsxiaoshi.com/index.php`，请求体是 AES-128-CBC、ZeroPadding、Base64 编码的 JSON，认证同时依赖 token 和 `PHPSESSID` Cookie。

## 本阶段已完成

### 后端协议与业务层

- 新增 [dazi_dto.py](../../src/backend/models/dto/dazi_dto.py)：比赛类型、登录结果、赛文、上传结果 DTO。
- 新增 [dazi_client.py](../../src/backend/integration/dazi_client.py)：
  - AES-128-CBC + UTF-8 + ZeroPadding；
  - 登录 `Api/User/login`；
  - 载文 `Api/Text/getContent`；
  - 上传 `Api/Rank/uploadResult`；
  - 明文响应解析；
  - `trust_env=False`；
  - HTTP Cookie 发送和登录响应 Cookie 提取。
  - 载文/上传响应中的轮换 `PHPSESSID` 返回给 Gateway。
- 新增 [dazi_provider.py](../../src/backend/ports/dazi_provider.py) Port。
- 新增 [dazi_config.py](../../src/backend/config/dazi_config.py)，并接入 [runtime_config.py](../../src/backend/config/runtime_config.py) 的 `dazi` 配置段。
- 新增 [dazi_gateway.py](../../src/backend/application/gateways/dazi_gateway.py)：
  - token 使用 `dazi_token` 密钥环项；
  - Cookie 使用 `dazi_cookie` 密钥环项；
  - 用户名/展示名和非秘密设置写入 `config.json`；
  - 密码不持久化。
- 新增 [dazi_usecases.py](../../src/backend/application/usecases/dazi_usecases.py)：
  - 52dazi 赛文载入用例；
  - 显式成绩上传用例；
  - `SessionStat` 快照到 `resultPostData` 字段映射；
  - `MM:SS.sss` 用时格式；
  - 52dazi 键准公式。
  - 上传业务字段包含规范化的 `competitionType`。

### Qt/QML 接入

- 新增 [dazi_adapter.py](../../src/backend/presentation/adapters/dazi_adapter.py)，登录、载文、上传均走 `BaseWorker`。
- [container.py](../../src/backend/config/container.py) 已装配 Dazi client、gateway、use case、adapter。
- [main.py](../../main.py) 已将 `dazi_adapter` 注入 Bridge。
- [typing_adapter.py](../../src/backend/presentation/adapters/typing_adapter.py) 已在完成瞬间保存成绩、文本和标题快照，避免 QML 后续清空文本导致上传空数据。
- [bridge.py](../../src/backend/presentation/bridge.py) 已增加：
  - 登录/退出、载入赛文、上传成绩 Slot；
  - 登录态、上传态、当前默认比赛类型和成绩可上传状态属性；
  - Dazi 相关信号。
- [SettingsPage.qml](../../src/qml/pages/SettingsPage.qml) 已增加 52dazi 设置区：网关、输入法、默认比赛类型、上传开关、登录/退出。
- [ToolLine.qml](../../src/qml/typing/ToolLine.qml) 和 [TypingPage.qml](../../src/qml/pages/TypingPage.qml) 已增加“52dazi赛文”和“上传成绩”入口。

## 已验证

以下命令在本阶段完成：

```bash
python -m compileall -q src/backend main.py
uv run ruff check src/backend/config/dazi_config.py src/backend/integration/dazi_client.py src/backend/application/gateways/dazi_gateway.py src/backend/application/usecases/dazi_usecases.py src/backend/models/dto/dazi_dto.py src/backend/ports/dazi_provider.py src/backend/presentation/adapters/dazi_adapter.py src/backend/config/container.py src/backend/config/runtime_config.py src/backend/presentation/bridge.py src/backend/presentation/adapters/typing_adapter.py main.py
uv run pytest tests/test_crypt.py tests/test_runtime_config.py tests/test_qml_pages.py -q
```

结果：第一阶段为 `93 passed`；第二阶段新增 Dazi 专项测试后为 `35 passed`，Ruff 通过，Python 编译通过。

专项测试覆盖 AES 已知向量、三种竞赛编号、请求体与 Cookie、响应异常、网络错误、成绩字段边界、Worker 生命周期和真实 `QThreadPool` 信号送达。

## 下一阶段必须完成

### 1. 已完成协议与业务单测

实现：`tests/test_dazi_client.py` 已覆盖：

- AES 已知向量：ASCII、中文、空字符串、恰好 16 字节；
- 解密 `build_login_payload`、`build_content_payload`、`build_upload_payload`，断言公共字段和业务字段类型；
- `0/2/4` 三种比赛编号以及非法编号回退极速杯；
- 登录响应字符串/对象错误、缺 token、非法 JSON；
- 赛文命名字段 `a_name/a_content/a_author` 和数字字段 `0/1/6/7`；
- 上传响应 `msg` 为字符串和对象两种形式；
- 网络超时、连接错误、非 2xx；
- 本地 mock HTTP 服务检查 URL、纯文本加密 body、Cookie。

实现：`tests/test_dazi_usecases.py` 已覆盖：

- 完整 `resultPostData` 字段集合；
- `wordNum == len(content)`；
- `typingTime` 格式；
- 键准公式、零击键、零用时、20 字符输入法截断；
- 未登录、上传关闭、空标题/空正文。

实现：`tests/test_dazi_adapter.py` 已覆盖 Worker 成功、失败清理、登录态、防重复上传和真实线程池信号送达；适配器持有 `_active_workers` 引用直到 `finished`。

### 2. 已修复的实现缺口

当前代码审查发现：

- 载文/上传后的轮换 Cookie 由 `DaziGateway` 回存到 `dazi_cookie`。
- 上传 payload 显式包含赛文对应的 `competitionType`。
- 默认网关常量移到 `ports.dazi_provider`，解除配置层对 Integration 的依赖。
- Worker 现在先连接所有信号，再交给线程池启动；`updateConfig` 收敛为三个参数。
- Dazi 资格现在只允许已登录、开关开启、当前 Dazi 全文赛文完成；切换普通文本、分片、乱序或剪贴板文本时清除资格。
- 未实现自动重登：认证失败由 UI 提示用户重新登录，密码不写配置、不进入长期内存，也不未经确认引入环境变量自动登录。

### 3. 待完成的真实 UI/网关验证

运行：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python main.py
```

重点观察：

- 设置页打开时 ComboBox 当前项是否正确同步；
- 登录失败后按钮是否恢复可用；
- 登录成功后密码框是否清空；
- 切换普通文本后上传成绩按钮是否立即禁用；
- 载入 Dazi 赛文、完成全文跟打、点击上传后是否只出现一次请求；
- 网络错误时本地历史是否仍然保存；
- Linux 无密钥环环境下是否优雅失败。

真实网关验证必须使用测试账号，禁止日志输出 token、Cookie、密码。真实测试最好沿用 dazitui 的协议顺序：登录 -> 载文 -> 完成模拟成绩 -> 上传。

## 工作区注意事项

本工作区在本阶段开始前已经存在用户改动和未跟踪文件，包括 `CHANGELOG.md`、`README.md`、Wayland bridge 相关文件及 [只读调查报告.md](../../只读调查报告.md)。不要回滚这些文件，也不要把无关改动纳入本功能重构。

本阶段没有提交 Git commit。下一 agent 接手时先运行：

```bash
git status --short
git diff --stat
```

然后优先补测试和修复“下一阶段必须完成”中的协议缺口，再考虑更新 `ARCHITECTURE.md`、`docs/reference/config.md`、`docs/reference/bridge-slots.md` 和 `CHANGELOG.md`。
