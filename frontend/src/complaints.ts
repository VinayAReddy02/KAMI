import { useEffect, useState } from "react";
import { api } from "./api";
import type { Complaint } from "./types";

/** Citizen pipe-damage tickets, refreshed every 10 seconds. */
export function useComplaints(): { complaints: Complaint[]; loading: boolean; error: string | null } {
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const pull = () =>
      api
        .complaints()
        .then((c) => alive && (setComplaints(c), setError(null)))
        .catch((e: Error) => alive && setError(e.message))
        .finally(() => alive && setLoading(false));
    pull();
    const id = window.setInterval(pull, 10000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);
  return { complaints, loading, error };
}
