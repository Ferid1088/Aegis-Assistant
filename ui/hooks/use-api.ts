"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<Error | null>(null);

  const reload = useCallback(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    api
      .get<T>(path)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e as Error); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [path]);

  useEffect(() => reload(), [reload]);

  return { data, loading, error, reload };
}
