/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { ink: '#092b35', coral: '#ff765e', sand: '#fff5e6', moss: '#31755f' }, boxShadow: { float: '0 18px 50px rgba(9,43,53,.12)' } } },
  plugins: []
}

