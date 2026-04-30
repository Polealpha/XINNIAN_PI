# Qwen3-Omni BF16 / AutoRound 切换

当前约定：

- 远端现网端口固定：`8091`
- BF16 模型：`Qwen3-Omni-30B-A3B-Instruct`
- AutoRound 模型：`Intel/Qwen3-Omni-30B-A3B-Instruct-int4-AutoRound`
- AutoRound 需要先做一次 **runtime-fix**（覆盖 BF16 的 tokenizer / preprocessor 元数据），脚本会自动处理。

## 本地一键切换

在 Windows PowerShell 里执行：

```powershell
Set-Location 'E:\Desktop\lunwen_qwen_publish'
.\scripts\switch_remote_qwen_omni.ps1 -Mode bf16
```

或：

```powershell
Set-Location 'E:\Desktop\lunwen_qwen_publish'
.\scripts\switch_remote_qwen_omni.ps1 -Mode autoround
```

脚本会：

1. 通过 `E:\codex_ssh_helper.ps1` 连接远端
2. 停掉当前 `8091`
3. 按模式切换模型
4. 轮询 `http://127.0.0.1:8091/v1/models`
5. 输出当前 `max_model_len`

## 当前推荐值

### BF16

- `max_model_len = 24576`

### AutoRound runtime-fix

- `max_model_len = 131072`

## 已验证结果

### BF16

- 能稳定恢复现网
- 当前上下文：`24576`

### AutoRound runtime-fix

- 原始 checkpoint 直接加载会因为 tokenizer / processor 元数据不兼容而失败
- runtime-fix 后可启动
- 已实测通过：
  - `65536`
  - `98304`
  - `131072`

## 微信适配层快速探针

可用下面命令查看本机当前微信桥接状态：

```powershell
Set-Location 'E:\Desktop\lunwen_qwen_publish'
.\scripts\probe_wechat_bridge.ps1
```

它会输出：

- 当前 `openclaw_state` 根目录
- `openclaw.json` provider / auth profile
- `openclaw-weixin` 状态目录是否存在
- 已发现的 QR 资源
- 本机可疑的 WeChat / pywechat / pyweixin 运行时痕迹
