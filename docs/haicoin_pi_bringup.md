# Haicoin 树莓派联调配置与启动方案

这份说明针对当前这台尚未做过实体验证的树莓派，目标是先把 **摄像头 + ST7789 + I2S 麦克风 + 双舵机** 跑起来，再逐步打开主人识别和后端联动。

## 当前已知硬件

- Raspberry Pi（用户提供 IP：`172.16.2.160`）
- 摄像头：已接入
- 屏幕：ST7789 320x240 SPI
- 麦克风：I2S 麦克风
- 云台舵机：2 个
  - 左右旋转舵机：用户说接在 `pin32`
  - 前后倾斜舵机：用户说接在 `pin33`

## 关键映射结论

### 1. 舵机 pin32 / pin33 的解释
项目里的 GPIO 配置使用的是 **BCM 编号**，而树莓派接线时很多人说的 `pin32` / `pin33` 常常是 **物理针脚号**。

如果用户说的是物理针脚：

- 物理 `pin32` → BCM `12`
- 物理 `pin33` → BCM `13`

这正好和仓库里 `config/pi_zero2w.st7789.example.json` / `config/pi_zero2w.audio_only.json` 的 GPIO 舵机示例一致。

所以当前建议先按下面配置：

- pan servo GPIO = `12`
- tilt servo GPIO = `13`

### 2. ST7789 的引脚以 `st7789_test_luma.txt` 为准
用户明确说屏幕配置参考 `st7789_test_luma.txt`，其中关键配置是：

- `port=0`
- `device=0`
- `gpio_DC=24`
- `gpio_RST=25`
- `bus_speed_hz=40000000`
- `width=320`
- `height=240`
- `rotate=0`

注意：这和仓库里 `config/pi_zero2w.st7789.example.json` 里的示例引脚不同。

**因此当前项目配置优先采用测试文件里的屏幕引脚：**

- `spi_dc_gpio = 24`
- `spi_reset_gpio = 25`
- `spi_backlight_gpio = null`

## 建议使用的配置文件

已整理好建议配置文件：

- `config/pi_zero2w.haicoin-rig.json`

它基于现有示例做了这些调整：

- 打开摄像头
- 打开音频采集
- 使用 GPIO 方式控制双舵机
- 使用 ST7789 作为显示驱动
- 屏幕引脚按 `st7789_test_luma.txt`
- 暂时关闭物理按钮，避免和未知接线冲突

## 配置摘要

### 音频

```json
"audio": {
  "enabled": true,
  "sample_rate": 16000,
  "channels": 1,
  "command": ["arecord", "-q", "-D", "default", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw"]
}
```

说明：

- 这是当前项目默认的单声道 16k 采集链路
- 你的 I2S 麦克风是否正好暴露为 `default`，还需要上机验证
- 如果树莓派上 I2S 设备不是默认声卡，后续要把 `-D default` 改成类似 `hw:1,0` 或 `plughw:1,0`

### 摄像头

```json
"camera": {
  "enabled": true,
  "backend": "picamera2",
  "device_index": 0,
  "width": 320,
  "height": 240,
  "fps": 4
}
```

说明：

- 初次联调建议 `320x240 @ 4fps`
- 分辨率和帧率保守一点，更适合 Zero 2 W 先跑通

### 舵机

```json
"hardware": {
  "driver": "gpio",
  "pan_servo": {
    "enabled": true,
    "gpio_pin": 12,
    "min_angle": 45,
    "max_angle": 135,
    "center_angle": 90
  },
  "tilt_servo": {
    "enabled": true,
    "gpio_pin": 13,
    "min_angle": 65,
    "max_angle": 165,
    "center_angle": 90
  }
}
```

说明：

- 这里按物理 `pin32/pin33` → BCM `12/13`
- 舵机正反方向和角度范围还需要上机微调
- 如果出现左右反了、俯仰反了，优先改 `min/max/center` 或在代码里做反向映射

### 屏幕

```json
"ui": {
  "display_driver": "st7789",
  "expression_width": 320,
  "expression_height": 240,
  "spi_port": 0,
  "spi_device": 0,
  "spi_dc_gpio": 24,
  "spi_reset_gpio": 25,
  "spi_backlight_gpio": null,
  "spi_rotation": 0,
  "spi_bus_speed_hz": 40000000,
  "display_fps": 12
}
```

说明：

- 这里完全跟 `st7789_test_luma.txt` 对齐
- 没有额外配置背光控制脚
- 如果屏幕实际接了 BLK 脚，后续再补 `spi_backlight_gpio`

## 推荐启动顺序

不要一上来就全功能一把梭。建议按下面顺序验证。

### 阶段 1：最小运行时验证
目标：确认服务能启动，不崩。

```bash
cd ~/XINNIAN_PI
source .venv/bin/activate
python -m pi_runtime.server --config config/pi_zero2w.haicoin-rig.json --engine-config config/engine_config.json
```

启动后先看：

- 服务是否成功监听 `8090`
- 有没有导入失败
- 有没有 ST7789 初始化报错
- 有没有音频采集命令报错
- 有没有摄像头初始化报错

### 阶段 2：本地接口探活
在树莓派本机执行：

```bash
curl http://127.0.0.1:8090/healthz
curl http://127.0.0.1:8090/status
curl http://127.0.0.1:8090/expression/state
```

看点：

- 服务是否活着
- `display_state` 是否 ready
- `voice_state` / `wake_state` 是否初始化成功
- `health.audio_ok` / `health.video_ok` 是否正常

### 阶段 3：摄像头验证

```bash
curl -o preview.jpg http://127.0.0.1:8090/camera/preview.jpg
```

如果能抓到图，说明摄像头主链路通了。

### 阶段 4：屏幕验证
如果服务起来但屏幕没显示：

1. 先单独跑 `st7789_test_luma.txt` 对应测试脚本，确认硬件引脚没问题
2. 再回到项目里排查 `display_surface.py`

也就是说：

- **测试脚本通，项目不通** → 项目配置或渲染适配问题
- **测试脚本也不通** → 接线 / SPI / 权限 / 驱动层问题

### 阶段 5：舵机验证
先不要开自动跟随，手动打接口：

```bash
curl -X POST http://127.0.0.1:8090/pan_tilt \
  -H 'Content-Type: application/json' \
  -d '{"pan":0.3,"tilt":0.0}'

curl -X POST http://127.0.0.1:8090/pan_tilt \
  -H 'Content-Type: application/json' \
  -d '{"pan":-0.3,"tilt":0.0}'

curl -X POST http://127.0.0.1:8090/pan_tilt \
  -H 'Content-Type: application/json' \
  -d '{"pan":0.0,"tilt":0.25}'
```

如果方向反了：

- 左右反了：调 pan 的角度范围
- 上下反了：调 tilt 的角度范围

### 阶段 6：音频 / 麦克风验证
先看 `arecord` 默认设备是否可用：

```bash
arecord -l
arecord -L
```

如果默认设备不对，修改配置里的：

```json
"command": ["arecord", "-q", "-D", "<你的设备名>", ...]
```

再测：

```bash
curl http://127.0.0.1:8090/voice/status
curl -X POST http://127.0.0.1:8090/voice/transcribe_recent -H 'Content-Type: application/json' -d '{"window_ms":4000}'
```

## 是否要启后端
当前建议分两步。

### 第一步：先不把重点放在后端联动
虽然配置文件里保留了：

```json
"backend": {
  "enabled": true,
  "base_url": "http://127.0.0.1:8000"
}
```

但如果树莓派上 backend 还没准备好，第一次联调可以先把它关掉：

```json
"backend": {
  "enabled": false,
  "base_url": "http://127.0.0.1:8000"
}
```

这样更适合先打通本地硬件链路。

### 第二步：硬件都通了，再启 backend
等摄像头 / 屏幕 / 舵机 / 麦克风都确认没问题，再启动：

```bash
python scripts/bootstrap_server_backend.py
python server_backend/run_server.py
```

然后再把 runtime 配置里的 backend 打开。

## 我对你这台树莓派的推荐方案

### 推荐主配置
- 用：`config/pi_zero2w.haicoin-rig.json`

### 推荐第一次联调策略
1. 先只跑 `pi_runtime`
2. 先验证屏幕、摄像头、舵机、麦克风
3. 后端联动放第二阶段
4. 主人识别先保留配置，但不作为第一轮验证重点

## 当前最大不确定项

我现在看到最需要上机确认的只有三件事：

1. **I2S 麦克风的 ALSA 设备名** 是否真的是 `default`
2. **ST7789 的 DC / RST 引脚** 是否确实与测试脚本一致
3. **你说的 pin32 / pin33** 是否确实指物理针脚，而不是 BCM 32 / 33

其中第 3 个我现在已经按“物理针脚”来配置，因为这和项目示例正好吻合。

## 下一步建议

最合适的下一步不是继续纸面分析，而是：

1. 把 `config/pi_zero2w.haicoin-rig.json` 传到树莓派
2. 在树莓派上直接启动 runtime
3. 逐项验证：屏幕 / 摄像头 / 舵机 / 麦克风
4. 根据实际报错再收敛配置

如果你愿意，下一步我可以直接继续帮你出：

- **树莓派首次联调命令清单**（一条条可以直接复制执行）
- **硬件排障顺序表**
- **把 backend 也一起纳入的双服务启动方案**
