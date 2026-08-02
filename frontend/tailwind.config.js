/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Fraunces", "Georgia", "serif"],
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
      colors: {
        gold: {
          50: "#FBF7EF",
          100: "#F3E8D3",
          200: "#E6D0A8",
          300: "#D6B378",
          400: "#C69C57",
          500: "#B08640",
          600: "#8F6B32",
          700: "#6E5227",
          800: "#4F3B1C",
          900: "#332612",
        },
      },
      boxShadow: {
        soft: "0 1px 2px rgba(28,25,23,0.04), 0 8px 24px -8px rgba(28,25,23,0.10)",
        elevated: "0 2px 4px rgba(28,25,23,0.05), 0 16px 40px -12px rgba(28,25,23,0.16)",
      },
    },
  },
  plugins: [],
};
