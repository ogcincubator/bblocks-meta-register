import type { UseFetchOptions } from 'nuxt/app';

export function useApi<T>(path: string | (() => string), options?: UseFetchOptions<T>) {
  const config = useRuntimeConfig();
  return useFetch(path, {
    baseURL: config.public.apiBase,
    ...options,
  });
}
