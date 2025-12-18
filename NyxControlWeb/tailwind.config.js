/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        discord: {
          bg: '#36393f',
          dark: '#2f3136',
          darker: '#202225',
          light: '#40444b',
          blurple: '#5865F2',
          green: '#57F287',
          red: '#ED4245',
        }
      }
    },
  },
  plugins: [],
}
