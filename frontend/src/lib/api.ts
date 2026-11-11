export class ApiError extends Error {
	status: number;
	data: any;
	constructor(status: number, message: string, data: any = null) {
		super(message);
		this.status = status;
		this.data = data;
	}
}

async function request<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
	const headers: Record<string, string> = { 'X-Kern': '1' };
	let payload: BodyInit | undefined;
	if (body instanceof FormData) payload = body;
	else if (body !== undefined) {
		headers['Content-Type'] = 'application/json';
		payload = JSON.stringify(body);
	}
	let res: Response;
	try {
		res = await fetch('/api' + path, { method, headers, body: payload, ...init });
	} catch {
		throw new ApiError(0, 'Cannot reach the server.');
	}
	if (!res.ok) {
		let detail = res.statusText;
		let data: any = null;
		try {
			data = await res.json();
			detail = data.detail ?? detail;
		} catch {
			/* not json */
		}
		throw new ApiError(res.status, detail, data);
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

export const api = {
	get: <T>(path: string) => request<T>('GET', path),
	post: <T>(path: string, body?: unknown, init?: RequestInit) => request<T>('POST', path, body ?? {}, init),
	patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
	put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
	del: <T>(path: string) => request<T>('DELETE', path),
	upload(file: File) {
		const form = new FormData();
		form.append('file', file);
		return request<{ id: string; url: string; name: string; mime: string; size: number }>(
			'POST', '/files', form
		);
	}
};

export function qs(params: Record<string, string | number | undefined | null>): string {
	const u = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
	const s = u.toString();
	return s ? '?' + s : '';
}
