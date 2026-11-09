export interface SearchResultItem {
	conversation_id: string;
	platform: string;
	title: string;
	project_path?: string;
	header_path: string;
	chunk_text: string;
	score: number;
	started_at: string;
	relative_path?: string;
	topic_id?: string;
	topic_name?: string;
}


export interface ConversationSummary {
	id: string;
	external_id: string;
	platform: string;
	title: string;
	project_path?: string;
	git_branch?: string;
	model?: string;
	started_at: string;
	updated_at: string;
	message_count: number;
	relative_path?: string;
	token_summary?: Record<string, any>;
	raw_metadata?: Record<string, any>;
}

export interface ConversationMessage {
	step_index: number;
	role: string;
	content: string;
	reasoning_content?: string;
	tool_calls?: Array<{
		name: string;
		input?: any;
		output?: any;
		is_error?: boolean;
		duration_ms?: number;
	}>;
	attachments?: any[];
	sources?: any[];
	token_usage?: Record<string, any>;
	created_at?: string;
}

export interface ConversationDetail {
	id: string;
	external_id: string;
	platform: string;
	title: string;
	project_path?: string;
	git_branch?: string;
	model?: string;
	device?: string;
	started_at: string;
	updated_at: string;
	relative_path?: string;
	content_markdown?: string;
	raw_metadata?: Record<string, any>;
	token_summary?: Record<string, any>;
	messages?: ConversationMessage[];
}

export interface DeviceStat {
	device: string;
	conversations: number;
	last_sync?: string;
}

export interface RecentSyncItem {
	id: string;
	platform: string;
	title: string;
	project_path?: string;
	device?: string;
	message_count: number;
	updated_at: string;
	/** When the server actually persisted this sync (server clock) - the real
	 * sync-health signal, as opposed to updated_at which tracks the content's
	 * own message timestamps and stays old for backlog re-syncs. */
	last_ingested_at?: string;
}

export interface PlatformStat {
	platform: string;
	conversations: number;
	messages: number;
	chunks: number;
	latest_sync?: string;
}

export interface ArchiveStats {
	total_conversations: number;
	total_messages: number;
	total_chunks: number;
	platforms: PlatformStat[];
	devices?: DeviceStat[];
	recent_syncs?: RecentSyncItem[];
	generated_at: string;
}

export interface Topic {
	id: string;
	name: string;
	description?: string | null;
	keywords: string[];
	is_manual: boolean;
	count: number;
}

export interface TopicConversation {
	id: string;
	title: string;
	platform: string;
	started_at?: string | null;
	score: number;
	source: 'auto' | 'manual';
}

export interface TopicDetail {
	id: string;
	name: string;
	description?: string | null;
	keywords: string[];
	is_manual: boolean;
	conversations: TopicConversation[];
}

export interface TopicSuggestion {
	id: string;
	title: string;
	platform: string;
	started_at?: string | null;
	score: number;
}

export interface SavedQuery {
	id: string;
	query_text: string;
	short_title: string;
	execution_count: number;
	last_executed_at: string;
	created_at: string;
}

export interface ComputeWorkerInfo {
	name: string;
	url: string | null;
	latency_ms: number | null;
	status: 'online' | 'offline';
	model: string;
}

export interface SystemStatus {
	device: string;
	database_connected: boolean;
	compute_worker: ComputeWorkerInfo;
	pending_embed_tasks: number;
}

export interface TopicTimelineItem {
	period: string;
	count: number;
}

export interface TopicContextExport {
	topic: TopicDetail;
	timeline: TopicTimelineItem[];
	conversations_count: number;
	markdown: string;
}


