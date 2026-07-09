// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({

  // ssr: false,
  modules: ['@nuxt/fonts', 'vuetify-nuxt-module', '@nuxt/eslint'],
  devtools: { enabled: true },

  app: {
    head: {
      style: [
        // vuetify-nuxt-module injects component <style> tags before the CSS array runs,
        // so layer order must be declared here to arrive first in the document.
        { innerHTML: '@layer tailwind-theme, tailwind-reset, vuetify-core, vuetify-components, vuetify-overrides, vuetify-utilities, tailwind-utilities, vuetify-final;' },
      ],
    },
  },

  css: [
    'vuetify/styles',
    'assets/styles/tailwind.css',
  ],

  runtimeConfig: {
    public: {
      apiBase: 'http://localhost:8000',
    },
  },
  compatibilityDate: '2025-12-21',

  postcss: {
    plugins: {
      '@tailwindcss/postcss': {},
    },
  },

  eslint: {
    config: {
      import: {
        package: 'eslint-plugin-import-lite',
      },
      stylistic: {
        semi: true,
      },
    },
  },

  vuetify: {
    moduleOptions: {
      styles: { configFile: 'assets/styles/settings.scss' },
    },
    vuetifyOptions: {
      theme: {
        defaultTheme: 'dark', // default 'system' requires `ssr: false` to avoid hydration warnings
        utilities: false,
      },
      display: {
        mobileBreakpoint: 'md',
        thresholds: {
          xs: 0, sm: 600, md: 960, lg: 1280, xl: 1920, xxl: 2560,
        },
      },
    },
  },
});
