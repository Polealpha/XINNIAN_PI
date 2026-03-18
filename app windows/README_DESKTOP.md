# PC 桌面端打包/运行

前置：
- Node.js 18+（建议 20）
- npm 已安装

安装依赖：
```
npm install
```

开发调试（启动 Vite + Electron）：
```
npm run electron:dev
```

打包安装包（Windows）：
```
npm run electron:dist
```

产物位置：
- release/ 目录下的安装包

注意：
- 打包前会执行 `vite build`，确保 dist 是最新。
- 如果只想快速本地打开 dist：
  `npm run electron:pack`
