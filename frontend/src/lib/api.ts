import type {
  AsyncAccepted,
  ArticleGrade,
  ArticleGradeCard,
  AuthTokens,
  Bundle,
  GradingBoard,
  Invitation,
  Operation,
  PageResult,
  Role,
  SignalDetail,
  SignalSummary,
  User,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/v1").replace(/\/$/, "");
const ACCESS_KEY = "stormcloud.access";
const REFRESH_KEY = "stormcloud.refresh";

export class ApiError extends Error {
  readonly status: number;
  readonly problem?: unknown;

  constructor(status: number, message: string, problem?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

function token(name: string): string | null {
  return window.localStorage.getItem(name);
}

function remember(tokens: AuthTokens): void {
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  if (tokens.refresh_token) window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

export function clearSession(): void {
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

export function hasSession(): boolean {
  return Boolean(token(ACCESS_KEY) || token(REFRESH_KEY));
}

async function decodeError(response: Response): Promise<ApiError> {
  const contentType = response.headers.get("content-type") ?? "";
  let payload: unknown;
  if (contentType.includes("json")) {
    payload = await response.json().catch(() => undefined);
  } else {
    payload = await response.text().catch(() => undefined);
  }
  const data = payload as { detail?: unknown; title?: string } | undefined;
  const message =
    typeof data?.detail === "string"
      ? data.detail
      : data?.title || response.statusText || "Request failed";
  return new ApiError(response.status, message, payload);
}

async function refreshAccess(): Promise<boolean> {
  const refreshToken = token(REFRESH_KEY);
  if (!refreshToken) return false;
  const response = await fetch(API_BASE + "/auth/refresh", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    clearSession();
    return false;
  }
  remember((await response.json()) as AuthTokens);
  return true;
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  auth?: boolean;
  retryAuth?: boolean;
  idempotencyKey?: string;
};

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const access = token(ACCESS_KEY);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.auth !== false && access) headers.set("Authorization", "Bearer " + access);
  if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);

  const response = await fetch(API_BASE + path, {
    ...options,
    headers,
    credentials: "include",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 401 && options.auth !== false && options.retryAuth !== false) {
    if (await refreshAccess()) return request<T>(path, { ...options, retryAuth: false });
  }
  if (!response.ok) throw await decodeError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestBlob(path: string, retryAuth = true): Promise<Blob> {
  const headers = new Headers();
  const access = token(ACCESS_KEY);
  if (access) headers.set("Authorization", "Bearer " + access);
  const response = await fetch(API_BASE + path, {
    headers,
    credentials: "include",
  });
  if (response.status === 401 && retryAuth && await refreshAccess()) {
    return requestBlob(path, false);
  }
  if (!response.ok) throw await decodeError(response);
  return response.blob();
}

function normalizePage<T>(value: PageResult<T> | T[]): PageResult<T> {
  return Array.isArray(value) ? { items: value } : value;
}

interface BackendDocument {
  id: string;
  canonical_url: string;
  media_type: string;
  retrieved_at: string;
  content_sha256: string;
  text: string;
}

interface BackendHighlight {
  id: string;
  kind: "human" | "automatic";
  start_offset: number;
  end_offset: number;
  text_verbatim: string;
  tombstoned_at?: string | null;
  created_at?: string;
}

interface BackendEdge {
  id: string;
  target_id: string;
  kind: string;
  weight?: number | null;
}

async function loadSignalDetail(id: string): Promise<SignalDetail> {
  const signal = await request<SignalDetail>("/signals/" + id);
  const [document, highlights, neighbors] = await Promise.all([
    signal.document_version_id
      ? request<BackendDocument>("/documents/" + signal.document_version_id)
      : Promise.resolve(undefined),
    request<BackendHighlight[]>("/signals/" + id + "/highlights"),
    request<BackendEdge[]>("/signals/" + id + "/neighbors"),
  ]);
  return {
    ...signal,
    canonical_url: document?.canonical_url ?? signal.canonical_url,
    document_version: document
      ? {
          id: document.id,
          canonical_url: document.canonical_url,
          media_type: document.media_type,
          content_hash: document.content_sha256,
          normalized_text: document.text,
          retrieved_at: document.retrieved_at,
        }
      : undefined,
    highlights: highlights.map((item) => ({
      id: item.id,
      kind: item.kind === "automatic" ? "auto" : "human",
      start_offset: item.start_offset,
      end_offset: item.end_offset,
      text: item.text_verbatim,
      active: !item.tombstoned_at,
      created_at: item.created_at,
    })),
    neighbors: neighbors.map((edge) => ({
      id: edge.id,
      target_id: edge.target_id,
      score: edge.weight ?? 0,
      edge_type: edge.kind,
    })),
  };
}

export const api = {
  auth: {
    async login(email: string, password: string): Promise<User> {
      const result = await request<AuthTokens>("/auth/login", {
        method: "POST",
        auth: false,
        body: { email, password },
      });
      remember(result);
      return result.user ?? request<User>("/auth/me");
    },
    acceptInvite(invitationToken: string, password: string) {
      return request<AuthTokens>("/auth/accept-invite", {
        method: "POST",
        auth: false,
        body: { token: invitationToken, password },
      }).then((result) => {
        remember(result);
        return result;
      });
    },
    me: () => request<User>("/auth/me"),
    async logout(): Promise<void> {
      const refreshToken = token(REFRESH_KEY);
      try {
        await request<void>("/auth/logout", {
          method: "POST",
          body: { refresh_token: refreshToken },
          retryAuth: false,
        });
      } finally {
        clearSession();
      }
    },
  },
  signals: {
    list: (query = "") =>
      request<PageResult<SignalSummary> | SignalSummary[]>("/signals" + query).then(normalizePage),
    get: loadSignalDetail,
    create: (url: string, description: string) =>
      request<AsyncAccepted>("/signals", {
        method: "POST",
        body: { url, description_verbatim: description },
        idempotencyKey: crypto.randomUUID(),
      }),
    retry: (id: string) =>
      request<AsyncAccepted>("/signals/" + id + "/retry", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      }),
    archive: (id: string) => request<void>("/signals/" + id + "/archive", { method: "POST" }),
    neighbors: (id: string) => request<NonNullable<SignalDetail["neighbors"]>>("/signals/" + id + "/neighbors"),
    addHighlight: (id: string, start: number, end: number, text: string) =>
      request<AsyncAccepted>("/signals/" + id + "/highlights", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: { start_offset: start, end_offset: end, text_verbatim: text },
      }),
    removeHighlight: (signalId: string, highlightId: string) =>
      request<AsyncAccepted>("/signals/" + signalId + "/highlights/" + highlightId, {
        method: "DELETE",
      }),
    suppressAuto: (signalId: string, highlightId: string, suppressed: boolean) =>
      request<AsyncAccepted>(
        "/signals/" + signalId + "/auto-highlights/" + highlightId + "/suppress",
        { method: suppressed ? "POST" : "DELETE" },
      ),
  },
  grading: {
    board: () => request<GradingBoard>("/articles/grading-board"),
    update: (signalId: string, grade: ArticleGrade | null, expectedRevision?: string) =>
      request<ArticleGradeCard>("/signals/" + signalId + "/grade", {
        method: "PUT",
        body: {
          grade,
          ...(expectedRevision ? { expected_revision: expectedRevision } : {}),
        },
        idempotencyKey: crypto.randomUUID(),
      }),
    thumbnail: (signalId: string) =>
      requestBlob("/signals/" + signalId + "/thumbnail"),
  },
  bundles: {
    list: () => request<PageResult<Bundle> | Bundle[]>("/bundles").then(normalizePage),
    get: (id: string) => request<Bundle>("/bundles/" + id),
    create: (input: {
      thesis?: string;
      ordered: boolean;
      items: Array<{ url: string; note?: string; position: number }>;
    }) =>
      request<AsyncAccepted>("/bundles", {
        method: "POST",
        body: input,
        idempotencyKey: crypto.randomUUID(),
      }),
    retry: (id: string) =>
      request<AsyncAccepted>("/bundles/" + id + "/retry", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      }),
    archive: (id: string) => request<void>("/bundles/" + id + "/archive", { method: "POST" }),
  },
  operations: {
    get: (id: string) => request<Operation>("/operations/" + id),
  },
  admin: {
    listInvitations: () =>
      request<PageResult<Invitation> | Invitation[]>("/admin/invitations").then(normalizePage),
    invite: (email: string, role: Role, expiresInHours: number) =>
      request<Invitation>("/admin/invitations", {
        method: "POST",
        body: { email, role, expires_in_hours: expiresInHours },
        idempotencyKey: crypto.randomUUID(),
      }),
    revokeInvitation: (id: string) =>
      request<void>("/admin/invitations/" + id, { method: "DELETE" }),
    listUsers: () => request<PageResult<User> | User[]>("/admin/users").then(normalizePage),
    updateUser: (id: string, patch: { role?: Role; active?: boolean }) =>
      request<User>("/admin/users/" + id, {
        method: "PATCH",
        body: {
          ...(patch.role ? { role: patch.role } : {}),
          ...(patch.active === undefined ? {} : { is_active: patch.active }),
        },
      }),
    },
};
