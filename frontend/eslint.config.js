import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import eslintConfigPrettier from 'eslint-config-prettier'

// Dates are written only by utils/dates.ts and utils/dateFormat.ts, in the
// pattern chosen in Settings → Appearance. A number's toLocaleString() can't be
// told from a date's by syntax, so only `new Date(…).toLocaleString()` is
// caught; the date-only and time-only forms exist only on dates.
const DATE_FORMATTING = [
  {
    selector:
      'CallExpression[callee.property.name=/^toLocale(Date|Time)String$/]',
    message: 'Format dates with utils/dates (formatDate, formatTimestamp, …).',
  },
  {
    selector:
      "CallExpression[callee.property.name='toLocaleString'][callee.object.type='NewExpression'][callee.object.callee.name='Date']",
    message: 'Format dates with utils/dates (formatTimestamp, …).',
  },
  {
    selector:
      "NewExpression[callee.object.name='Intl'][callee.property.name='DateTimeFormat']",
    message: 'Format dates with utils/dates (formatDate, formatTimestamp, …).',
  },
]

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
    files: ['src/**/*.{ts,tsx}'],
    ignores: [
      'src/utils/dates.ts',
      'src/utils/dateFormat.ts',
      '**/*.test.{ts,tsx}',
    ],
    rules: { 'no-restricted-syntax': ['warn', ...DATE_FORMATTING] },
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
        // Repeated: this block's list replaces the one above for these files.
        ...DATE_FORMATTING,
      ],
    },
  },
  eslintConfigPrettier,
)
