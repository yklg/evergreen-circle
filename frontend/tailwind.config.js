/** @type {import('tailwindcss').Config} */

// 莫兰迪设计 token —— 只注册一份扁平命名（handbook 可直接粘贴）。
// 命名刻意不含产品名：令牌里编进品牌名 ⇒ 每次改名都要重命名一遍 CSS 面（见 docs/ARCHITECTURE.md）。
// 曾另挂 `verda: palette` 命名空间，实测 `*-verda-*` 工具类零消费 ⇒ 同色双真相，已删。
const palette = {
  primary: '#7C9885',
  'primary-soft': '#A8C0A8',
  'primary-tint': '#EAF1EA',
  'primary-deep': '#5E7A66',
  sun: '#F4E2B8',
  'sun-soft': '#FBF6E9',
  ink: '#3A413C',
  'ink-2': '#6B746C',
  'ink-3': '#9AA39C',
  line: '#E3E8E3',
  bg: '#FAFBF9',
  card: '#FFFFFF',
  ok: '#8AB58A',
  warn: '#E0B775',
  risk: '#CE9A92',
  info: '#8FA8C0',
}

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ...palette,
      },
      borderRadius: {
        card: '16px',
        btn: '12px',
        chip: '999px',
      },
      boxShadow: {
        card: '0 4px 24px rgba(124,152,133,0.08)',
        float: '0 8px 40px rgba(124,152,133,0.14)',
        glow: '0 0 0 4px rgba(124,152,133,0.12)',
      },
      fontFamily: {
        sans: ['Inter', 'Noto Sans SC', 'PingFang SC', 'sans-serif'],
        serif: ['Noto Serif SC', 'Georgia', 'serif'],
        mono: ['JetBrains Mono', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        h1: ['28px', { lineHeight: '1.3', fontWeight: '600' }],
        h2: ['22px', { lineHeight: '1.3', fontWeight: '600' }],
        h3: ['18px', { lineHeight: '1.3', fontWeight: '600' }],
        body: ['15px', { lineHeight: '1.7' }],
        aux: ['13px', { lineHeight: '1.6' }],
        tag: ['11px', { lineHeight: '1.4' }],
      },
      spacing: {
        4.5: '18px',
      },
      maxWidth: {
        content: '1440px',
        read: '760px',
      },
      transitionTimingFunction: {
        smooth: 'cubic-bezier(.4,0,.2,1)',
      },
      keyframes: {
        breath: { '0%,100%': { opacity: '1' }, '50%': { opacity: '.55' } },
        floatUp: {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        glow: {
          '0%,100%': { boxShadow: '0 0 0 0 rgba(124,152,133,.4)' },
          '50%': { boxShadow: '0 0 0 8px rgba(124,152,133,0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        spinSlow: { to: { transform: 'rotate(360deg)' } },
      },
      animation: {
        breath: 'breath 2s ease-in-out infinite',
        floatUp: 'floatUp .4s cubic-bezier(.4,0,.2,1) both',
        glow: 'glow 1.8s ease-in-out infinite',
        shimmer: 'shimmer 1.6s linear infinite',
        'spin-slow': 'spinSlow 8s linear infinite',
      },
    },
  },
  plugins: [],
}
