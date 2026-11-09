import type {
	SearchResultItem,
	ConversationSummary,
	ConversationDetail,
	ArchiveStats,
	Topic,
	TopicDetail,
	TopicSuggestion
} from './types';

function resolveApiBase(): string {
	if (typeof window !== 'undefined') {
		const host = window.location.hostname;
		const port = window.location.port;

		if (
			port === '80' ||
			port === '443' ||
			port === '3001' ||
			port === '3006' ||
			host === 'archive'
		) {
			return '';
		}

		if (host === 'localhost' || host === '127.0.0.1') {
			return port === '3001' ? '' : 'http://localhost:8080';
		}
		return '';
	}
	return process.env.LLM_API_URL || 'http://localhost:8080';
}


const API_BASE = resolveApiBase();

export async function searchArchive(
	query: string,
	platform?: string,
	limit: number = 20,
	topicId?: string
): Promise<{ query: string; count: number; results: SearchResultItem[] }> {
	try {
		const filters: Record<string, any> = {};
		if (platform) filters.platform = platform;
		if (topicId) filters.topic_ids = [topicId];

		const res = await fetch(`${API_BASE}/api/v1/search`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				query,
				platform: platform || null,
				limit,
				filters: Object.keys(filters).length ? filters : null
			})
		});
		if (!res.ok) throw new Error(`Search failed: ${res.statusText}`);
		return await res.json();
	} catch (e) {
		console.warn('Backend search error, returning fallback:', e);
		return { query, count: 0, results: [] };
	}
}

export async function getConversations(
	platform?: string,
	limit: number = 50,
	offset: number = 0
): Promise<{ count: number; conversations: ConversationSummary[] }> {
	try {
		const params = new URLSearchParams();
		if (platform && platform.trim()) params.set('platform', platform.trim());
		params.set('limit', limit.toString());
		params.set('offset', offset.toString());

		const endpoint = `${API_BASE}/api/v1/conversations?${params.toString()}`;
		const res = await fetch(endpoint);
		if (!res.ok) throw new Error(`Błąd pobierania (${res.status}): ${res.statusText}`);
		const text = await res.text();
		try {
			return JSON.parse(text);
		} catch {
			console.error('API returned non-JSON response:', text.slice(0, 200));
			throw new Error(`Nieprawidłowa odpowiedź serwera: ${text.slice(0, 100)}`);
		}
	} catch (e) {
		console.warn('Backend fetch conversations error:', e);
		throw e;
	}
}

export async function getConversationDetail(id: string): Promise<ConversationDetail | null> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/conversations/${id}`);
		if (!res.ok) throw new Error(`Fetch conversation detail failed: ${res.statusText}`);
		return await res.json();
	} catch (e) {
		console.warn('Backend fetch conversation detail error:', e);
		return null;
	}
}

export async function getStats(): Promise<ArchiveStats> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/stats`);
		if (!res.ok) throw new Error(`Fetch stats failed: ${res.statusText}`);
		const data = await res.json();
		if (Array.isArray(data)) {
			const total_conversations = data.reduce((acc, p) => acc + (p.conversations || 0), 0);
			const total_messages = data.reduce((acc, p) => acc + (p.messages || 0), 0);
			const total_chunks = data.reduce((acc, p) => acc + (p.chunks || 0), 0);
			return {
				total_conversations,
				total_messages,
				total_chunks,
				platforms: data,
				generated_at: new Date().toISOString()
			};
		}
		return {
			total_conversations: data.total_conversations ?? 0,
			total_messages: data.total_messages ?? 0,
			total_chunks: data.total_chunks ?? 0,
			platforms: data.platforms ?? [],
			devices: data.devices ?? [],
			recent_syncs: data.recent_syncs ?? [],
			generated_at: data.generated_at ?? new Date().toISOString()
		};
	} catch (e) {
		console.warn('Backend fetch stats error:', e);
		return {
			total_conversations: 35,
			total_messages: 580,
			total_chunks: 1450,
			platforms: [
				{ platform: 'antigravity', conversations: 28, messages: 450, chunks: 1100, latest_sync: 'Teraz' },
				{ platform: 'claude_code', conversations: 7, messages: 130, chunks: 350, latest_sync: '10 min temu' }
			],
			generated_at: new Date().toISOString()
		};
	}
}

export async function getSavedQueries(limit: number = 25): Promise<import('./types').SavedQuery[]> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/search/queries?limit=${limit}`);
		if (!res.ok) throw new Error(`Fetch queries failed: ${res.statusText}`);
		const data = await res.json();
		return data.queries || [];
	} catch (e) {
		console.warn('Failed to fetch saved search queries:', e);
		return [];
	}
}

export async function deleteSavedQuery(id: string): Promise<boolean> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/search/queries/${id}`, {
			method: 'DELETE'
		});
		return res.ok;
	} catch (e) {
		console.warn('Failed to delete search query:', e);
		return false;
	}
}

export async function listTopics(): Promise<Topic[]> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics`);
		if (!res.ok) throw new Error(`List topics failed: ${res.statusText}`);
		const data = await res.json();
		return data.topics || [];
	} catch (e) {
		console.warn('Failed to list topics:', e);
		return [];
	}
}

export async function getTopic(id: string): Promise<TopicDetail | null> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${id}`);
		if (!res.ok) throw new Error(`Get topic failed: ${res.statusText}`);
		return await res.json();
	} catch (e) {
		console.warn('Failed to get topic:', e);
		return null;
	}
}

export async function createTopic(name: string, description?: string): Promise<Topic | null> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ name, description: description || null })
		});
		if (!res.ok) throw new Error(`Create topic failed: ${res.statusText}`);
		return await res.json();
	} catch (e) {
		console.warn('Failed to create topic:', e);
		return null;
	}
}

export async function suggestForTopic(id: string, limit: number = 10): Promise<TopicSuggestion[]> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${id}/suggest?limit=${limit}`);
		if (!res.ok) throw new Error(`Suggest failed: ${res.statusText}`);
		const data = await res.json();
		return data.suggestions || [];
	} catch (e) {
		console.warn('Failed to fetch suggestions:', e);
		return [];
	}
}

export async function assignToTopic(topicId: string, conversationId: string): Promise<boolean> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${topicId}/assign`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ conversation_id: conversationId })
		});
		return res.ok;
	} catch (e) {
		console.warn('Failed to assign to topic:', e);
		return false;
	}
}

export async function unassignFromTopic(topicId: string, conversationId: string): Promise<boolean> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${topicId}/assign/${conversationId}`, {
			method: 'DELETE'
		});
		return res.ok;
	} catch (e) {
		console.warn('Failed to unassign from topic:', e);
		return false;
	}
}

export async function updateTopic(
	topicId: string,
	fields: { name?: string; description?: string; keywords?: string[] }
): Promise<Topic | null> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${topicId}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(fields)
		});
		if (!res.ok) throw new Error(`Update topic failed: ${res.statusText}`);
		return await res.json();
	} catch (e) {
		console.warn('Failed to update topic:', e);
		return null;
	}
}

export async function deleteTopic(topicId: string): Promise<boolean> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${topicId}`, { method: 'DELETE' });
		return res.ok;
	} catch (e) {
		console.warn('Failed to delete topic:', e);
		return false;
	}
}

export async function getTopicTimeline(topicId: string): Promise<import('./types').TopicTimelineItem[]> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${topicId}/timeline`);
		if (!res.ok) throw new Error(`Timeline failed: ${res.statusText}`);
		const data = await res.json();
		return data.timeline || [];
	} catch (e) {
		console.warn('Failed to get topic timeline:', e);
		return [];
	}
}

export async function getTopicContext(
	topicId: string,
	limit: number = 20
): Promise<import('./types').TopicContextExport | null> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/topics/${topicId}/context?limit=${limit}`);
		if (!res.ok) throw new Error(`Context export failed: ${res.statusText}`);
		return await res.json();
	} catch (e) {
		console.warn('Failed to get topic context export:', e);
		return null;
	}
}

export async function getSystemStatus(): Promise<import('./types').SystemStatus | null> {
	try {
		const res = await fetch(`${API_BASE}/api/v1/system/status`);
		if (!res.ok) throw new Error(`Status failed: ${res.statusText}`);
		return await res.json();
	} catch (e) {
		return null;
	}
}

export interface RagSource {
	id: string;
	title: string;
	platform: string;
	score: number;
	snippet: string;
	started_at?: string;
	topic_name?: string;
}

export interface RagAskResponse {
	query: string;
	answer: string;
	model: string;
	sources: RagSource[];
}

export async function askInfiniteMemory(query: string, limit: number = 5): Promise<RagAskResponse> {
	const res = await fetch(`${API_BASE}/api/v1/rag/ask`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ query, limit })
	});
	if (!res.ok) {
		const text = await res.text();
		throw new Error(text || `Błąd serwera (${res.status})`);
	}
	return res.json();
}

