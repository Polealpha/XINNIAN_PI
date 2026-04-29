import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(() => {
    return {
      base: "./",
      server: {
        port: 3001,
        host: '0.0.0.0',
      },
      build: {
        rollupOptions: {
          input: {
            main: path.resolve(__dirname, 'index.html'),
            visualfocusDemo: path.resolve(__dirname, 'visualfocus-demo.html'),
            qwenRealtimeDemo: path.resolve(__dirname, 'qwen-realtime-demo.html'),
          },
        },
      },
      plugins: [react()],
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      }
    };
});
