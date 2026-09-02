# Wayland 浏览器击键桥接

> 用本机 evdev 服务补足 Wayland + 中文输入法下网页无法看到的物理击键。

## 安装

1. 将 [typetype-wayland-bridge.user.js](../../scripts/typetype-wayland-bridge.user.js) 安装到 Tampermonkey、Violentmonkey 等用户脚本管理器。
2. 启动本机服务：

   ```bash
   uv run python scripts/wayland_typing_bridge.py
   ```

3. 将终端输出的 `token` 填入油猴脚本的 `CONFIG.token`。token 保存在 `~/.config/typetype/wayland-typing-bridge-token`，文件权限为用户私有。
4. 刷新目标网页并确认右下角显示 `已连接`。

## 我爱打字网适配

当前油猴脚本内置支持 `https://www.52dazi.cn` 的以下页面：

- `/`、`/home`：普通跟打
- `/battle/*`：极速战场
- `/practice`：词库练习

普通跟打和战场页通过网站现有 Vuex `racing/typing` action 补入 Wayland 丢失的物理击键；词库练习页补入组件的 `keyCount` / `lastKeyCount`。油猴脚本会将可信原生 `keydown` 与物理事件按时间配对：已被网站统计的按键不重复补入，先到的物理事件会在原生事件随后到达时回滚网站重复计数。

桥接无法恢复被浏览器屏蔽按键的具体 `KeyboardEvent.code`。普通字符会归入 `Unidentified`，总击键、击键速度和码长可以修正，但 `/summary` 中的字母键热力图和左右手分布不能还原；退格仍会准确归入 `Backspace`。

服务固定绑定 `127.0.0.1:8765`，不接受局域网连接。若希望额外限制网页来源，可以启动时指定 Origin：

```bash
uv run python scripts/wayland_typing_bridge.py --origin https://typing.example.com
```

## 设备权限

服务需要读取键盘对应的 `/dev/input/event*`。如果启动时提示找不到设备：

```bash
sudo usermod -aG input "$USER"
```

重新登录后再启动服务，也可以用 `--device /dev/input/by-id/...` 指定设备。

## 协议

油猴脚本通过 `GM_xmlhttpRequest` 请求本机 `/events` 长轮询端点，避免 HTTPS 页面连接 `ws://127.0.0.1` 时被浏览器混合内容策略拦截。请求携带 token 和当前网页 Origin：

```text
GET http://127.0.0.1:8765/events?token=<token>&since=<cursor>
X-Typetype-Origin: https://www.52dazi.cn
```

服务端返回 JSON，不发送具体键码：

```json
{"version":1,"cursor":12,"events":[{"type":"key","kind":"stroke","timestamp":1720000000000,"sequence":12}]}
```

油猴脚本只在页面可见且可编辑元素获得焦点时消费事件。它会在文档上派发 `typetype:physical-key`：

```js
document.addEventListener("typetype:physical-key", (event) => {
  const physical = JSON.parse(event.detail);
  // physical.kind: "stroke" | "backspace"
  // physical.strokes / physical.backspaces: 当前输入框会话累计值
});
```

脚本不会伪造 `keydown`，也不会阻止网页原本的 `input` / `compositionend` 事件。除内置的我爱打字网适配外，其他网页跟打器需要在自己的适配层消费上述事件，并将其用于码长、击键和退格统计。

## 隐私边界

- 服务固定只监听回环地址。
- token 和 Origin 都会校验；省略 `--origin` 时仍必须提供正确 token。
- 事件仅包含 `stroke` / `backspace` 聚合值，不包含字符、键码、设备名或文本内容。
- 服务不写入按键日志；没有网页客户端连接时，事件直接丢弃；长轮询客户端只在内存中缓存最近 128 条事件。
- 油猴脚本只有在当前页面可见且输入控件聚焦时才累计并派发事件。
