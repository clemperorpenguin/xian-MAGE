/*
 * Vitest configuration for MASHA's browser-free core/ tests.
 * No browser or DOM — pure algorithmic tests.
 */

import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/core/**/*.test.ts', 'test/**/*.test.ts'],
    exclude: ['node_modules', 'dist'],
  },
});
