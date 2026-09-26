# 和弦模式统计功能实施计划

## 1. 目标

在设置页增加“和弦模式”开关。

开启后，打字统计按“和弦”作为一次逻辑击键：多个手指同时按下组成一个和弦时，无论该和弦包含多少个物理按键，都只计为 1 次击键，并据此重新计算击键速度、码长和相关统计结果。

关闭后，保持现有普通打字统计行为不变。

## 2. 当前代码现状

当前统计链路如下：

```text
SettingsPage.qml
    -> RuntimeConfig
    -> Bridge
    -> TypingAdapter
    -> TypingService
    -> SessionStat
```

当前击键统计来源有两类：

1. 普通平台
   - `src/qml/typing/LowerPane.qml` 监听文本变化。
   - 文本发生用户输入变化时调用 `appBridge.handlePressed()`。
   - 因此通常按文本变化事件统计。

2. Wayland/macOS 特殊平台
   - 全局键盘监听器监听物理按键。
   - `GlobalKeyListener` 或 `MacKeyListener` 发出 `keyPressed`。
   - `Bridge.on_key_received()` 调用 `TypingAdapter.handlePressed()`。
   - 当前会把每个物理按键分别计入 `key_stroke_count`。

统计核心位置：

- `src/backend/domain/services/typing_service.py`
  - 保存和累积 `key_stroke_count`。
  - 处理文本提交、删除、完成判断和历史记录。
- `src/backend/models/entity/session_stat.py`
  - `keyStroke = key_stroke_count / time`。
  - `codeLength = key_stroke_count / char_count`。
  - `keyAccuracy` 使用 `codeLength` 折算回改成本。
- `src/backend/presentation/adapters/typing_adapter.py`
  - 对外暴露统计接口。
  - 转发按键、文本提交和统计信号。
- `src/backend/presentation/bridge.py`
  - 接收 QML 和全局监听器事件。
  - 暴露 QML 属性和 Slot。
- `src/backend/config/runtime_config.py`
  - `config.json` 的唯一主要序列化入口。
- `src/qml/pages/SettingsPage.qml`
  - 设置页 UI。

## 3. 第一阶段统计口径

### 3.1 和弦模式下

- 一个和弦视为一次逻辑击键。
- 和弦中包含几个物理按键，不影响逻辑击键次数。
- 一次提交一个字符时，增加 1 次逻辑击键。
- 一次提交多个字符时，按本次提交的字符数量增加逻辑击键数。
- 一次退格仍视为 1 次逻辑击键，并增加退格次数。
- 速度按逻辑击键数计算：

  ```text
  击键 = 逻辑击键数 / 用时
  ```

- 码长按逻辑击键数计算：

  ```text
  码长 = 逻辑击键数 / 已输入字数
  ```

- 键准继续使用新的码长计算回改成本。
- 字数、错字数、回改次数、退格次数、用时的基本含义保持不变。
- 历史记录、分片统计、完成快照、峰值统计和 52dazi 成绩数据使用新的逻辑击键结果。

### 3.2 普通模式下

- 保持现有 `handlePressed()` 和 `key_stroke_count` 行为。
- 不改变已有普通键盘、输入法、Wayland、macOS 统计结果。

## 4. 需要在实现前确认的边界

以下问题需要在正式编码前确认，避免把“和弦”错误实现成简单的时间窗口去重：

1. 和弦是否由最终上屏字符定义
   - 推荐：以一次最终提交的字符或字符串作为一次和弦输入结果。
   - 这样可以覆盖普通平台、Wayland、macOS 和中文输入法路径。

2. 一次和弦是否可能产生多个字符
   - 如果一个和弦可以直接产生多个字符，需要确认是计 1 次击键，还是按产生的字符数计数。
   - 当前计划暂按“一个和弦对应一个逻辑字符；一次提交多个字符按字符数计数”处理。

3. 空提交或预编辑变化是否计数
   - 推荐：预编辑变化、空提交、输入法内部状态变化不计逻辑击键。
   - 只有实际产生文本的提交才计入正向逻辑击键。

4. 退格是否属于和弦
   - 当前计划：退格单独计 1 次逻辑击键。
   - 如果用户将退格也作为和弦的一部分，需要后续单独定义退格和弦协议。

5. 粘贴、批量输入和程序化设置文本是否计数
   - 推荐：粘贴或程序化设置文本不作为用户和弦击键统计。
   - 需要保留现有 `suppressTextChanged` 等保护逻辑。

6. 设置开关何时生效
   - 推荐：开关立即保存，但只对下一次统计事件生效。
   - 已经完成的会话不重新换算历史击键数。
   - 如需切换后立即清空当前统计，需要另行确认，当前计划不这样处理。

## 5. 配置设计

建议在 `RuntimeConfig` 中增加独立的打字配置段：

```json
{
    "typing": {
        "chord_mode_enabled": false
    }
}
```

建议新增：

```python
@dataclass
class TypingConfig:
    chord_mode_enabled: bool = False
```

需要完成：

- `RuntimeConfig` 增加 `typing` 字段。
- `_from_dict()` 读取 `typing.chord_mode_enabled`。
- `_to_dict()` 写入 `typing.chord_mode_enabled`。
- 缺少字段时默认 `False`。
- 对非法 JSON 类型使用现有 `_safe_bool()` 容错。
- 不修改 schema 版本，保持已有配置兼容。
- 配置写入仍统一经 `RuntimeConfig`，不要在 UI 侧直接写文件。

## 6. Bridge 与设置页设计

### 6.1 Bridge

增加：

- `chordModeChanged = Signal()`。
- `@Property(bool, notify=chordModeChanged)` 的 `chordModeEnabled`。
- `@Slot(bool)` 的 `setChordModeEnabled(enabled)`。

实现要求：

- 从 `RuntimeConfig.typing.chord_mode_enabled` 读取当前值。
- 设置变更后调用配置更新方法并持久化。
- 发出 `chordModeChanged`，使设置页能够同步状态。
- Bridge 只做属性代理和 Slot 转发，不直接承载统计业务逻辑。

### 6.2 SettingsPage.qml

在现有设置页增加“打字统计”或同等语义的设置分组，并加入 Switch：

- 标题：`和弦模式`。
- 说明：多个手指同时按下视为一次击键，并按和弦击键数计算码长。
- 初始值绑定 `appBridge.chordModeEnabled`。
- `onCheckedChanged` 调用 `appBridge.setChordModeEnabled(checked)`。
- 使用同步保护变量，避免 Bridge 信号回写时重复保存。
- 增加 `Connections`，监听 `onChordModeChanged` 并同步 Switch。

## 7. 统计层设计

### 7.1 TypingService

在纯业务层增加显式的模式配置或逻辑击键入口，避免把和弦判断散落在 QML 和 Bridge 中。

推荐方向：

- 保留现有 `accumulate_key()` 作为普通模式的单物理键统计入口。
- 增加面向逻辑事件的入口，例如：

  ```python
  accumulate_logical_key(count: int = 1)
  ```

- 或在 `handle_committed_text()` 中由 Adapter 根据模式传入本次逻辑击键数。
- 和弦模式下，正向提交根据实际提交字符数增加逻辑击键。
- 删除路径由显式退格事件增加 1 次逻辑击键。
- 不要直接修改 `SessionStat.codeLength` 公式来“事后修正”击键数。

### 7.2 TypingAdapter

负责将配置和输入事件转换为统计层所需的逻辑事件：

- 注入或读取当前和弦模式配置。
- 普通模式继续兼容当前 `handlePressed()` 调用。
- 和弦模式下避免全局监听器的每个物理键重复计数。
- 文本实际提交后，按逻辑提交量增加击键。
- 退格事件单独处理一次。
- 统计信号继续由 `_emit_typing_signals()` 统一发射。

需要特别检查：

- `handle_committed_text()` 的返回值和完成判断。
- `handleLoadedText()` 的清零顺序。
- `prepare_for_text_load()` 的异步文本清空保护。
- `handleStartStatus()` 的开始、暂停和恢复逻辑。
- `_check_typing_complete()` 中的完成快照。

## 8. 平台输入路径处理

### 8.1 普通平台 QML 路径

`LowerPane.qml` 当前在 `onTextChanged` 中调用 `handlePressed()`。

需要明确区分：

- 普通模式：保持现有路径和计数行为。
- 和弦模式：实际文本提交时走逻辑击键计数，预编辑变化不计数。
- 程序化设置文本时继续受 `suppressTextChanged` 保护。

### 8.2 Wayland/macOS 全局监听路径

当前 `Bridge.on_key_received()` 对每个 `keyPressed` 都调用 `handlePressed()`。

和弦模式下必须避免多个物理键分别累加。建议通过以下方式之一实现，编码前根据确认后的口径选择：

1. 推荐方案：全局监听只负责启动会话、退格和标点辅助信息；正向逻辑击键由最终文本提交统一统计。
2. 如果必须在物理键阶段统计和弦，需要扩展监听协议，提供按下/抬起状态和同一和弦的按键集合，再增加和弦聚合器。

当前代码只有单键 `keyPressed`，没有通用的 key-up 事件和和弦集合事件，因此不应直接假设现有监听器已经能够识别和弦。

涉及文件：

- `src/backend/ports/key_listener.py`
- `src/backend/integration/global_key_listener.py`
- `src/backend/integration/mac_key_listener.py`
- `src/backend/presentation/bridge.py`
- `src/backend/presentation/adapters/typing_adapter.py`

## 9. 需要避免的实现方式

- 不要只修改 `SessionStat.codeLength` 的分母或公式。
- 不要在统计完成后根据字符数回头覆盖 `key_stroke_count`，否则会影响速度、键准、峰值和历史快照的一致性。
- 不要让 QML、Bridge、全局监听器分别维护各自的和弦计数。
- 不要把配置直接写入 `config.json`，必须通过 `RuntimeConfig`。
- 不要在没有 key-up 或事件边界定义的情况下，仅凭固定时间窗口推断所有和弦。
- 不要破坏普通模式已有的首键启动、退格计数、标点标顶、暂停恢复和输入法兼容逻辑。
- 不要在 `TypingService.clear()` 中清零 `char_count` 和 `wrong_char_count`，遵守项目现有异步 `onTextChanged` 陷阱约束。

## 10. 测试计划

### 10.1 配置测试

在 `tests/test_runtime_config.py` 增加：

- 默认配置的和弦模式为关闭。
- `typing.chord_mode_enabled=true` 能正确读取。
- `typing.chord_mode_enabled=false` 能正确读取。
- 非法类型通过 `_safe_bool()` 回退到默认值。
- `_to_dict()` 和 `_from_dict()` 往返保持配置值。
- 保存后重新加载仍保持配置值。

### 10.2 领域统计测试

在现有 TypingService 或 SessionStat 测试中增加：

- 普通模式现有击键统计行为不变。
- 和弦模式提交一个字符增加 1 次逻辑击键。
- 和弦模式一次提交多个字符时，逻辑击键数符合最终定义。
- 和弦模式下码长按逻辑击键数计算。
- 和弦模式下击键速度按逻辑击键数计算。
- 和弦模式下键准中的回改折算使用新的码长。
- 和弦模式下退格增加一次逻辑击键和一次退格次数。
- 文本加载、分片切换后统计正确归零。
- 暂停恢复不会重复计数或丢失计数。

### 10.3 Bridge 和平台事件测试

在 `tests/test_backend.py` 或相关测试中增加：

- Bridge 暴露和弦模式属性。
- Bridge 设置开关后更新配置并发出变化信号。
- 普通平台首个输入仍能启动会话并计数。
- Wayland/macOS 普通模式每个有效物理按键仍计一次。
- 和弦模式下多个物理按键不会重复累加。
- 修饰键、导航键和快捷键过滤行为不受破坏。
- 退格行为保持正确。

### 10.4 QML 静态检查

在 `tests/test_qml_pages.py` 或现有 QML 检查中增加：

- 设置页包含和弦模式开关。
- Switch 绑定 `appBridge.chordModeEnabled`。
- Switch 调用 `appBridge.setChordModeEnabled()`。
- 存在 `onChordModeChanged` 同步逻辑。

## 11. 文档同步

完成代码后按项目规则检查并更新：

- `docs/ARCHITECTURE.md`：若新增配置字段、统计层职责或输入事件协议，补充架构事实。
- `docs/reference/`：若存在运行时配置或 Bridge 属性速查表，补充 `chord_mode_enabled`、`chordModeEnabled` 和 `setChordModeEnabled`。
- `AGENTS.md`：只有发现新的长期编码陷阱时才追加。
- `CHANGELOG.md`：属于用户可见功能时追加条目。

## 12. 实施顺序

1. 先确认第 4 节中的和弦边界，特别是“一次和弦产生多个字符”的统计规则。
2. 增加 `TypingConfig` 及配置读写测试。
3. 增加 Bridge 属性、Slot 和信号。
4. 增加设置页开关和 QML 同步逻辑。
5. 在统计层增加逻辑击键入口。
6. 接入普通平台文本提交路径。
7. 接入 Wayland/macOS 全局按键路径，消除和弦重复计数。
8. 补齐会话、分片、历史和完成快照测试。
9. 更新架构/reference/CHANGELOG 文档。
10. 执行完整验证。

## 13. 验收标准

功能完成必须满足：

- 设置页可以开启和关闭和弦模式。
- 设置重启后仍然保留。
- 和弦模式开启时，一个和弦只计一次逻辑击键。
- 和弦数量不会被错误地按物理按键数重复计算。
- 码长和击键速度使用逻辑击键数。
- 历史记录、分片结果、完成快照和成绩数据口径一致。
- 普通模式结果不发生回归。
- Wayland、macOS 和普通 QML 输入路径没有重复计数。
- 现有测试全部通过，并新增覆盖配置、统计和输入路径的测试。

## 14. 验证命令

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

如修改了 QML，还需要运行项目现有的 QML 页面测试，并在可用环境中实际打开设置页和跟打页验证开关、统计数字及会话切换行为。
