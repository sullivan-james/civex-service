#!/usr/bin/env node
// Fails if any Tailwind arbitrary-value colour utility (e.g. text-[#ff0000])
// or arbitrary font size (e.g. text-[10px]) shows up in frontend/src/**/*.tsx.
// Type sizes come from the scale in src/index.css; colours belong in the semantic tokens
// defined by the @theme block in src/index.css — see UI-AUDIT.md for the
// full token list and the mapping used by the original codemod.

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = join(fileURLToPath(import.meta.url), '..', '..')
const srcDir = join(frontendRoot, 'src')

const PATTERN =
  /(\btext-\[\d+(\.\d+)?(px|rem)\]|(text|bg|border|ring|outline|fill|stroke|divide|from|via|to|shadow|decoration|accent|caret)-\[(#[0-9a-fA-F]{3,8}|rgba?\([^\])]*\))\]|\b(fill|stroke|color|stopColor|floodColor)="#[0-9a-fA-F]{3,8}")/g

function collectTsxFiles(dir) {
  const files = []
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry)
    const stat = statSync(fullPath)
    if (stat.isDirectory()) {
      files.push(...collectTsxFiles(fullPath))
    } else if (entry.endsWith('.tsx')) {
      files.push(fullPath)
    }
  }
  return files
}

const violations = []
for (const file of collectTsxFiles(srcDir)) {
  const lines = readFileSync(file, 'utf8').split('\n')
  lines.forEach((line, index) => {
    for (const match of line.matchAll(PATTERN)) {
      violations.push({
        file: relative(frontendRoot, file),
        line: index + 1,
        token: match[0],
      })
    }
  })
}

if (violations.length > 0) {
  console.error('Hardcoded colour or font-size literal(s) found:\n')
  for (const { file, line, token } of violations) {
    console.error(`  ${file}:${line}  ${token}`)
  }
  console.error(
    '\nUse a semantic colour token instead of an arbitrary hex value — see the ' +
      "--color-* tokens defined in frontend/src/index.css's @theme block, and " +
      'the mapping in frontend/UI-AUDIT.md.',
  )
  process.exit(1)
}
