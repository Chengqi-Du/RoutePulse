import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { cpSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [react(), {
    name: 'copy-map-assets',
    apply: 'build',
    writeBundle(options) {
      const output = resolve(options.dir || 'dist', 'src')
      for (const folder of ['noto-road-map/json', 'noto-road-map/img', 'rescue-route-map/data']) {
        const destination = resolve(output, folder)
        mkdirSync(destination, { recursive: true })
        cpSync(resolve('src', folder), destination, { recursive: true })
      }
    },
  }],
})
