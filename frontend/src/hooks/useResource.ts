import { useCallback, useEffect, useRef, useState } from "react";

export function useResource<T>(loader: () => Promise<T>, dependencies: unknown[] = []) {
  const loaderRef = useRef(loader);
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loaderRef.current = loader;
  });

  const reload = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setData(await loaderRef.current());
    } catch (reason) {
      setError(reason);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void reload());
    // Dependencies are deliberately supplied by the caller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, ...dependencies]);

  return { data, error, loading, reload, setData };
}
