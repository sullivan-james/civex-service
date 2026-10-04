import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import eslintConfigPrettier from 'eslint-config-prettier'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    // One component per concept: use ui/ Button, IconButton, DataTable, TabNav
    // and Card instead of raw elements. Warn while pages are migrated.
    files: ['src/**/*.tsx'],
    ignores: ['src/components/ui/**', '**/*.test.tsx'],
    rules: {
      'no-restricted-syntax': [
        'warn',
        {
          selector: "JSXOpeningElement[name.name='button']",
          message:
            'Use <Button>, <IconButton> or <Card to=...> from components/ui.',
        },
        {
          selector: "JSXOpeningElement[name.name='table']",
          message: 'Use <DataTable> from components/ui.',
        },
        {
          selector: "JSXOpeningElement[name.name='details']",
          message:
            'Split large pages into tabs (<TabNav>); explain with <InfoTip>.',
        },
      ],
    },
  },
  eslintConfigPrettier,
)
