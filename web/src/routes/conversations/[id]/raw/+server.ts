import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ params }) => {
	try {
		const apiBase = process.env.LLM_API_URL || 'http://127.0.0.1:8080';
		const res = await fetch(`${apiBase}/api/v1/conversations/${params.id}`);
		if (!res.ok) {
			return new Response(`Błąd pobierania konwersacji (${res.status}): ${res.statusText}`, {
				status: res.status,
				headers: { 'Content-Type': 'text/plain; charset=utf-8' }
			});
		}
		const data = await res.json();
		return new Response(data.content_markdown || 'Brak treści markdown dla tej sesji.', {
			headers: {
				'Content-Type': 'text/plain; charset=utf-8'
			}
		});
	} catch (err: any) {
		return new Response(`Błąd serwera: ${err?.message || err}`, {
			status: 500,
			headers: { 'Content-Type': 'text/plain; charset=utf-8' }
		});
	}
};
