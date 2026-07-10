<script setup>
import {
  Activity,
  Download,
  ExternalLink,
  FileText,
  Play,
  RefreshCw,
  Search,
  Settings,
  Trash2,
  Upload,
} from "@lucide/vue";
import RelationGraph from "relation-graph/vue3";
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import {
  adminConfigs,
  adminStatus,
  apiBase,
  deleteFile,
  fileGraph,
  lightRagWebuiUrl,
  listFiles,
  retrieve,
  retryFile,
  schedulerLogs,
  schedulerStatus,
  triggerScheduler,
  updateConfigs,
  uploadFile,
} from "./api";

const tab = ref("workspace");
const files = ref([]);
const results = ref([]);
const retrievalTrace = ref(null);
const uploadQueue = ref([]);
const status = ref(null);
const configs = ref([]);
const scheduler = ref(null);
const logs = ref([]);
const selectedFileId = ref(null);
const graphTitle = ref("检索上下文");
const graph = ref({ nodes: [], edges: [] });
const graphRef = ref(null);
const selectedGraphNodeId = ref(null);
const centeredGraphNodeId = ref(null);
const message = ref("");
const pollTimer = ref(null);
const pollingStarting = ref(false);
const lastUpdatedAt = ref(null);
const syncActive = ref(false);
const loading = reactive({
  files: false,
  upload: false,
  retrieve: false,
  admin: false,
  trigger: false,
  graph: false,
});

const query = reactive({
  query: "",
  top_k: 5,
});

const primaryConfigKeys = [
  "rag.default_top_k",
  "rag.search_mode",
  "rag.chunk_size",
  "rag.chunk_overlap",
  "scheduler.batch_size",
  "scheduler.max_retries",
  "scheduler.retry_interval_minutes",
  "scheduler.processing_timeout_minutes",
];

const editableConfigs = computed(() =>
  configs.value.filter((item) => primaryConfigKeys.includes(item.key)),
);

const primaryConfigs = computed(() =>
  configs.value.filter((item) => primaryConfigKeys.includes(item.key)),
);

const advancedConfigs = computed(() =>
  editableConfigs.value.filter((item) => !primaryConfigKeys.includes(item.key)),
);

const failedFiles = computed(() =>
  files.value.filter((file) => file.index_status === "failed"),
);
const activeFiles = computed(() =>
  files.value.filter((file) =>
    ["pending", "processing", "deleting"].includes(file.index_status),
  ),
);
const selectedFile = computed(() =>
  files.value.find((file) => file.file_id === selectedFileId.value) || null,
);
const graphNodes = computed(() => graph.value.nodes || []);
const graphEdges = computed(() => graph.value.edges || []);
const traceKeywords = computed(() => retrievalTrace.value?.keywords || {});
const traceProcessing = computed(() => retrievalTrace.value?.processing_info || {});
const traceChunkStep = computed(() =>
  (retrievalTrace.value?.steps || []).find((step) => step.name === "chunk_sources") || null,
);
const graphSubtitle = computed(() => {
  if (selectedFile.value) return selectedFile.value.filename;
  if (graphTitle.value) return graphTitle.value;
  return "检索后自动生成";
});
const graphRootLabel = computed(() => {
  if (selectedFile.value) return selectedFile.value.filename;
  const text = query.query.trim();
  return text || "Query";
});
const graphDegree = computed(() => {
  const degree = {};
  for (const edge of graphEdges.value) {
    degree[edge.source] = (degree[edge.source] || 0) + 1;
    degree[edge.target] = (degree[edge.target] || 0) + 1;
  }
  return degree;
});
const rankedGraphNodes = computed(() =>
  [...graphNodes.value].sort((left, right) => {
    const leftScore =
      (left.source_segment_ids?.length || 0) * 10 + (graphDegree.value[left.id] || 0);
    const rightScore =
      (right.source_segment_ids?.length || 0) * 10 + (graphDegree.value[right.id] || 0);
    return rightScore - leftScore || left.label.localeCompare(right.label);
  }),
);
const graphNodeById = computed(() => {
  const byId = {};
  for (const node of graphNodes.value) byId[node.id] = node;
  return byId;
});
const selectedGraphNode = computed(() =>
  graphNodes.value.find((node) => node.id === selectedGraphNodeId.value) || null,
);
const selectedNodeEdges = computed(() => {
  if (!selectedGraphNodeId.value) return [];
  return graphEdges.value.filter(
    (edge) => edge.source === selectedGraphNodeId.value || edge.target === selectedGraphNodeId.value,
  );
});
const focusGraphNodeIds = computed(() => new Set());
const displayGraphNodes = computed(() => rankedGraphNodes.value);
const displayGraphEdges = computed(() => graphEdges.value);
const hiddenGraphSummary = computed(() => "");
const relationGraphOptions = {
  debug: false,
  allowSwitchLineShape: false,
  allowSwitchJunctionPoint: false,
  defaultLineShape: 4,
  defaultNodeShape: 0,
  defaultNodeColor: "transparent",
  defaultNodeWidth: 76,
  defaultNodeHeight: 76,
  defaultNodeBorderWidth: 0,
  defaultLineColor: "#94a3b8",
  defaultLineWidth: 1.5,
  layouts: [
    {
      layoutName: "center",
      max_per_width: 280,
      max_per_height: 120,
    },
  ],
};
const relationGraphData = computed(() => {
  const rootId =
    centeredGraphNodeId.value || rankedGraphNodes.value[0]?.id || "__empty_graph__";
  const nodes = graphNodes.value.map((node) => ({
    id: node.id,
    text: graphLabel(node.label, 18),
    data: {
      kind: isRagContextNode(node) ? "rag" : "expanded",
      entityType: node.entity_type || "",
      description: node.description || "",
      retrievalSource: node.retrieval_source || "",
      sourceCount: node.source_segment_ids?.length || 0,
    },
  }));
  const lines = graphEdges.value.map((edge) => {
    const isRagContext = isRagContextEdge(edge);
    return {
      id: edge.id,
      from: edge.source,
      to: edge.target,
      text: graphLabel(edge.relation_type || edge.keywords || "关系", 14),
      color: isRagContext ? "#d97706" : "#94a3b8",
      lineWidth: isRagContext ? 2 : 1.2,
      opacity: isRagContext ? 1 : 0.58,
      showEndArrow: false,
      data: edge,
    };
  });
  return { rootId, nodes, lines };
});
const graphLayout = computed(() => ({}));
const graphRootPosition = { x: 70, y: 250 };
const queryEntityLines = computed(() => []);

const pendingCount = computed(() => status.value?.files?.pending || 0);
const processingCount = computed(() => status.value?.files?.processing || 0);
const failedCount = computed(() => status.value?.files?.failed || 0);
const queuedCount = computed(() => pendingCount.value + processingCount.value);
const latestLog = computed(() => logs.value[0] || null);
const nextRunTime = computed(() => scheduler.value?.jobs?.[0]?.next_run_time || null);
const adminRunState = computed(() => {
  if (!scheduler.value?.running) return "调度器未启动";
  if (processingCount.value > 0) return "索引中";
  if (pendingCount.value > 0) return "有任务排队";
  return "空闲";
});

function maxRetries() {
  const item = configs.value.find((config) => config.key === "scheduler.max_retries");
  return item?.value || "-";
}

function setMessage(text) {
  message.value = text;
  if (text) {
    window.setTimeout(() => {
      if (message.value === text) message.value = "";
    }, 3500);
  }
}

function clearPolling() {
  if (pollTimer.value) {
    window.clearInterval(pollTimer.value);
    pollTimer.value = null;
  }
  syncActive.value = false;
}

async function refreshFiles() {
  loading.files = true;
  try {
    const payload = await listFiles();
    files.value = payload.items;
    lastUpdatedAt.value = new Date();
  } catch (error) {
    setMessage(`刷新文件失败：${error.message}`);
  } finally {
    loading.files = false;
  }
}

async function handleUpload(event) {
  const selected = Array.from(event.target.files || []);
  if (!selected.length) return;
  loading.upload = true;
  uploadQueue.value = selected.map((file) => ({ name: file.name, status: "pending" }));
  try {
    for (const [index, file] of selected.entries()) {
      uploadQueue.value[index].status = "uploading";
      try {
        await uploadFile(file);
        uploadQueue.value[index].status = "done";
      } catch (error) {
        uploadQueue.value[index].status = error.message;
      }
    }
    await refreshFiles();
    startFileStatusPolling();
  } finally {
    loading.upload = false;
    event.target.value = "";
  }
}

async function handleDelete(fileId) {
  try {
    await deleteFile(fileId);
    if (selectedFileId.value === fileId) {
      selectedFileId.value = null;
      graph.value = { nodes: [], edges: [] };
    }
    await refreshFiles();
    startFileStatusPolling({ includeAdmin: true });
  } catch (error) {
    setMessage(`删除失败：${error.message}`);
  }
}

async function handleRetry(fileId) {
  try {
    await retryFile(fileId);
    setMessage("已重新加入索引队列");
    await refreshFiles();
    startFileStatusPolling({ includeAdmin: true });
  } catch (error) {
    setMessage(`重试失败：${error.message}`);
  }
}

async function runRetrieve() {
  if (!query.query.trim()) return;
  loading.retrieve = true;
  try {
    const payload = await retrieve({
      query: query.query.trim(),
      top_k: query.top_k || undefined,
    });
    results.value = payload.chunks;
    retrievalTrace.value = payload.trace || null;
    selectedFileId.value = null;
    selectedGraphNodeId.value = null;
    centeredGraphNodeId.value = null;
    graphTitle.value = `检索：${query.query.trim()}`;
    graph.value = payload.graph || { nodes: [], edges: [] };
  } finally {
    loading.retrieve = false;
  }
}

async function loadGraph(fileId) {
  selectedFileId.value = fileId;
  selectedGraphNodeId.value = null;
  centeredGraphNodeId.value = null;
  retrievalTrace.value = null;
  graphTitle.value = "文件图谱";
  loading.graph = true;
  try {
    graph.value = await fileGraph(fileId);
  } catch (error) {
    graph.value = { nodes: [], edges: [] };
    setMessage(`加载图谱失败：${error.message}`);
  } finally {
    loading.graph = false;
  }
}

async function refreshAdmin() {
  loading.admin = true;
  try {
    const [statusPayload, configsPayload, schedulerPayload, logsPayload] =
      await Promise.all([
        adminStatus(),
        adminConfigs(),
        schedulerStatus(),
        schedulerLogs(),
      ]);
    status.value = statusPayload;
    configs.value = configsPayload;
    scheduler.value = schedulerPayload;
    logs.value = logsPayload.items;
    lastUpdatedAt.value = new Date();
  } catch (error) {
    setMessage(`刷新管理信息失败：${error.message}`);
  } finally {
    loading.admin = false;
  }
}

async function refreshAdminPage() {
  await Promise.all([refreshFiles(), refreshAdmin()]);
  if (hasActiveWork()) startFileStatusPolling({ includeAdmin: true });
}

async function saveConfigs() {
  const payload = {};
  for (const item of editableConfigs.value) payload[item.key] = item.value;
  configs.value = await updateConfigs(payload);
  setMessage("配置已保存");
}

async function triggerIndex() {
  loading.trigger = true;
  try {
    const result = await triggerScheduler();
    setMessage(result.message || "调度已触发");
    startFileStatusPolling({ includeAdmin: true });
  } catch (error) {
    setMessage(`触发失败：${error.message}`);
  } finally {
    loading.trigger = false;
  }
}

function hasActiveFiles() {
  return files.value.some((file) =>
    ["pending", "processing", "deleting"].includes(file.index_status),
  );
}

function hasActiveWork() {
  return hasActiveFiles() || pendingCount.value > 0 || processingCount.value > 0;
}

function fileProgress(file) {
  if (Number.isFinite(file.progress_percent)) {
    return Math.max(0, Math.min(100, file.progress_percent));
  }
  return 0;
}

function progressText(file) {
  const chunkText =
    file.progress_total_chunks && file.progress_processed_chunks != null
      ? ` (${file.progress_processed_chunks}/${file.progress_total_chunks})`
      : "";
  if (file.progress_message) return `${file.progress_message}${chunkText}`;

  const status = file.progress_stage || file.index_status;
  if (status === "pending") return "等待调度";
  if (status === "processing") return "索引中";
  if (status === "parsing") return "解析中";
  if (status === "chunking") return "分片中";
  if (status === "indexing") return "LightRAG 索引中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "deleting") return "清理中";
  if (status === "deleted") return "已删除";
  return status || "-";
}

function progressClass(file) {
  return `progress-fill ${file.progress_stage || file.index_status || "unknown"}`;
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatLastUpdated() {
  if (!lastUpdatedAt.value) return "尚未同步";
  return `最近同步 ${lastUpdatedAt.value.toLocaleTimeString()}`;
}

function shortError(file) {
  const text = file.error_msg || "-";
  return text.length > 90 ? `${text.slice(0, 90)}...` : text;
}

function shortDetails(details) {
  if (!details) return "-";
  const text = JSON.stringify(details);
  return text.length > 120 ? `${text.slice(0, 120)}...` : text;
}

function graphLabel(text, maxLength = 14) {
  const value = String(text || "");
  return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
}

function highlightTerms(item) {
  return [
    ...(item.highlights?.keywords || []),
    ...(item.highlights?.entities || []),
  ]
    .map((term) => String(term || "").trim())
    .filter((term, index, terms) => term && terms.indexOf(term) === index)
    .sort((left, right) => right.length - left.length)
    .slice(0, 24);
}

function highlightedContentParts(item) {
  const content = String(item.content || "");
  const terms = highlightTerms(item).filter((term) => content.includes(term));
  if (!terms.length) return [{ text: content, hit: false }];

  const parts = [];
  let index = 0;
  while (index < content.length) {
    const next = terms
      .map((term) => ({ term, at: content.indexOf(term, index) }))
      .filter((match) => match.at >= 0)
      .sort((left, right) => left.at - right.at || right.term.length - left.term.length)[0];
    if (!next) {
      parts.push({ text: content.slice(index), hit: false });
      break;
    }
    if (next.at > index) {
      parts.push({ text: content.slice(index, next.at), hit: false });
    }
    parts.push({ text: content.slice(next.at, next.at + next.term.length), hit: true });
    index = next.at + next.term.length;
  }
  return parts;
}

function isRagContextNode(node) {
  return ["lightrag_entity", "lightrag_relation_endpoint"].includes(node?.retrieval_source);
}

function isRagContextEdge(edge) {
  return edge?.retrieval_source === "lightrag_relationship";
}

function selectGraphNode(nodeId) {
  selectedGraphNodeId.value = selectedGraphNodeId.value === nodeId ? null : nodeId;
}

function focusGraphNode(nodeId) {
  selectedGraphNodeId.value = nodeId;
  centeredGraphNodeId.value = nodeId;
}

async function renderRelationGraph() {
  await nextTick();
  const graphInstance = graphRef.value?.getInstance?.();
  if (!graphInstance) return;

  if (!relationGraphData.value.nodes.length || !graphNodes.value.length) {
    graphInstance.clearGraph?.();
    return;
  }

  graphInstance.setJsonData(
    {
      rootId: relationGraphData.value.rootId,
      nodes: relationGraphData.value.nodes,
      lines: relationGraphData.value.lines,
    },
    true,
    () => {
      graphInstance.moveToCenter?.();
      graphInstance.zoomToFit?.();
    },
  );
}

function edgePosition() {
  return {
    source: { x: 250, y: 250 },
    target: { x: 250, y: 250 },
  };
}

watch([displayGraphNodes, displayGraphEdges, graphRootLabel, centeredGraphNodeId], () => {
  renderRelationGraph();
});

function startFileStatusPolling({ includeAdmin = false } = {}) {
  clearPolling();
  pollingStarting.value = true;
  syncActive.value = true;
  let tick = 0;
  const minTicks = 4;
  const maxTicks = 120;

  const refresh = async () => {
    tick += 1;
    const shouldRefreshAdmin = includeAdmin || tab.value === "admin";
    if (shouldRefreshAdmin) {
      await Promise.all([refreshFiles(), refreshAdmin()]);
    } else {
      await refreshFiles();
    }
    if ((tick >= minTicks && !hasActiveWork()) || tick >= maxTicks) {
      clearPolling();
    }
  };

  refresh();
  pollTimer.value = window.setInterval(refresh, 3000);
  pollingStarting.value = false;
}

function statusClass(value) {
  return `badge ${value || "unknown"}`;
}

onMounted(async () => {
  await Promise.all([refreshFiles(), refreshAdmin()]);
  if (hasActiveWork()) startFileStatusPolling({ includeAdmin: true });
});

onUnmounted(() => {
  clearPolling();
});
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <div>
        <h1>RAG 文件知识库</h1>
        <p>{{ apiBase }}</p>
      </div>
      <nav class="tabs">
        <button :class="{ active: tab === 'workspace' }" @click="tab = 'workspace'">
          <FileText :size="17" /> 工作台
        </button>
        <button :class="{ active: tab === 'admin' }" @click="tab = 'admin'">
          <Settings :size="17" /> 管理
        </button>
      </nav>
    </header>

    <div v-if="message" class="toast">{{ message }}</div>

    <section v-if="tab === 'workspace'" class="workspace-grid">
      <div class="workspace-main">
        <section class="panel retrieve-panel">
          <div class="panel-head">
            <h2>检索</h2>
            <button class="primary" :disabled="loading.retrieve" @click="runRetrieve">
              <Search :size="17" /> 检索
            </button>
          </div>
          <textarea v-model="query.query" placeholder="输入问题"></textarea>
          <div class="controls">
            <label>Top K <input v-model.number="query.top_k" type="number" min="1" max="50" /></label>
          </div>
        </section>

        <section class="panel graph-panel">
          <div class="panel-head">
            <h2>知识图谱</h2>
            <span class="subtle">{{ graphSubtitle }}</span>
          </div>
          <div v-if="selectedFile || graphNodes.length || loading.graph" class="graph-content">
            <div class="graph-canvas relation-graph-canvas">
              <RelationGraph
                v-if="graphNodes.length"
                ref="graphRef"
                :options="relationGraphOptions"
              >
                <template #node="{ node }">
                  <div
                    :class="['rg-rag-node', `rg-rag-node-${node.data?.kind || 'entity'}`]"
                    @click.stop="selectGraphNode(node.id)"
                    @dblclick.stop="focusGraphNode(node.id)"
                  >
                    <strong>{{ node.text }}</strong>
                    <span v-if="node.data?.entityType">
                      {{ graphLabel(node.data.entityType, 12) }}
                    </span>
                    <span v-else-if="node.data?.sourceCount">
                      来源 {{ node.data.sourceCount }} 个片段
                    </span>
                  </div>
                </template>
              </RelationGraph>
              <svg class="legacy-graph-svg" viewBox="0 0 500 500" role="img">
                <line
                  v-for="line in queryEntityLines"
                  :key="line.id"
                  class="query-link"
                  :x1="graphRootPosition.x"
                  :y1="graphRootPosition.y"
                  :x2="line.target.x"
                  :y2="line.target.y"
                />
                <line
                  v-for="edge in displayGraphEdges"
                  :key="edge.id"
                  class="relation-link"
                  :x1="edgePosition(edge).source.x"
                  :y1="edgePosition(edge).source.y"
                  :x2="edgePosition(edge).target.x"
                  :y2="edgePosition(edge).target.y"
                />
                <g class="root-node" :transform="`translate(${graphRootPosition.x}, ${graphRootPosition.y})`">
                  <circle r="30" />
                  <text text-anchor="middle" y="48">{{ selectedFile ? "文件" : "检索" }}</text>
                </g>
                <g
                  v-for="node in displayGraphNodes"
                  :key="node.id"
                  :class="focusGraphNodeIds.has(node.id) ? 'focus-node' : 'related-node'"
                  :transform="`translate(${graphLayout[node.id]?.x || 250}, ${graphLayout[node.id]?.y || 250})`"
                >
                  <circle :r="focusGraphNodeIds.has(node.id) ? 26 : 21" />
                  <text text-anchor="middle" y="42">{{ graphLabel(node.label) }}</text>
                </g>
              </svg>
              <div v-if="loading.graph" class="empty compact">正在加载图谱...</div>
              <div v-else-if="!graphNodes.length" class="empty compact">暂无实体关系数据</div>
              <div v-else class="graph-focus-note">
                LightRAG 实际检索图：实体为节点，关系为边，点击实体查看一跳关系
              </div>
            </div>
            <div class="graph-lists">
              <div v-if="selectedGraphNode" class="selected-node-card">
                <h3>选中实体</h3>
                <article>
                  <strong>{{ selectedGraphNode.label }}</strong>
                  <p>{{ selectedGraphNode.description || "-" }}</p>
                  <small>
                    一跳关系 {{ selectedNodeEdges.length }} 条
                  </small>
                </article>
                <article v-for="edge in selectedNodeEdges" :key="edge.id">
                  <strong>{{ edge.source }} → {{ edge.target }}</strong>
                  <p>{{ edge.relation_type || edge.keywords || "relation" }}：{{ edge.description || "-" }}</p>
                </article>
              </div>
              <div>
                <h3>完整实体 {{ displayGraphNodes.length }}</h3>
                <article v-for="node in displayGraphNodes" :key="node.id">
                  <strong>
                    <button
                      class="text-link"
                      @click="selectGraphNode(node.id)"
                      @dblclick="focusGraphNode(node.id)"
                    >
                      {{ node.label }}
                    </button>
                  </strong>
                  <small v-if="isRagContextNode(node)" class="rag-hit">RAG 命中实体</small>
                  <small v-if="node.entity_type">{{ node.entity_type }}</small>
                  <p>{{ node.description || "-" }}</p>
                  <small v-if="node.source_segment_ids?.length">
                    来源 {{ node.source_segment_ids.length }} 个片段
                  </small>
                </article>
              </div>
              <div>
                <h3>完整关系 {{ displayGraphEdges.length }}</h3>
                <article v-for="edge in displayGraphEdges" :key="edge.id">
                  <strong>{{ edge.source }} → {{ edge.target }}</strong>
                  <small v-if="isRagContextEdge(edge)" class="rag-hit">RAG 命中关系</small>
                  <p>{{ edge.relation_type || edge.keywords || "relation" }}：{{ edge.description || "-" }}</p>
                  <small v-if="Number.isFinite(edge.weight)">weight {{ edge.weight.toFixed(2) }}</small>
                  <small v-if="edge.source_segment_ids?.length">
                    来源 {{ edge.source_segment_ids.length }} 个片段
                  </small>
                </article>
                <div v-if="hiddenGraphSummary" class="graph-limit-note">
                  {{ hiddenGraphSummary }}
                </div>
              </div>
            </div>
          </div>
          <div v-else class="empty">检索后自动显示相关实体和关系，也可以从右侧选择文件图谱</div>
        </section>

        <section class="panel results-panel">
          <div class="panel-head">
            <h2>检索结果</h2>
            <span class="subtle">{{ results.length }} 条</span>
          </div>
          <div class="results">
            <article v-for="item in results" :key="item.segment_id" class="result-item">
              <div class="result-meta">
                <span>#{{ item.rank }}</span>
                <span v-if="Number.isFinite(item.score)">score {{ item.score.toFixed(3) }}</span>
                <span>{{ item.citation.filename }}</span>
                <span>{{ item.citation.location_type }} {{ item.citation.location }}</span>
              </div>
              <p class="result-content">
                <template
                  v-for="(part, partIndex) in highlightedContentParts(item)"
                  :key="`${item.segment_id}-${partIndex}`"
                >
                  <mark v-if="part.hit">{{ part.text }}</mark>
                  <span v-else>{{ part.text }}</span>
                </template>
              </p>
              <div
                v-if="item.highlights?.entities?.length || item.highlights?.relationships?.length"
                class="result-hit-tags"
              >
                <span v-for="entity in item.highlights?.entities || []" :key="`e-${entity}`">
                  实体 {{ entity }}
                </span>
                <span
                  v-for="relationship in item.highlights?.relationships || []"
                  :key="`r-${relationship}`"
                >
                  关系 {{ relationship }}
                </span>
              </div>
              <a :href="`${apiBase}${item.citation.download_url}`" target="_blank">下载原文</a>
            </article>
            <div v-if="!results.length" class="empty">暂无检索结果</div>
          </div>
        </section>

        <section v-if="retrievalTrace" class="panel trace-panel">
          <div class="panel-head">
            <h2>检索过程</h2>
            <span class="subtle">{{ retrievalTrace.mode }}</span>
          </div>
          <div class="trace-content">
            <div class="trace-summary">
              <div>
                <span>检索模式</span>
                <strong>{{ retrievalTrace.mode }}</strong>
                <p>{{ retrievalTrace.mode_description }}</p>
              </div>
              <div>
                <span>实体上下文</span>
                <strong>
                  {{ traceProcessing.total_entities_found ?? 0 }}
                  →
                  {{ traceProcessing.entities_after_truncation ?? 0 }}
                </strong>
              </div>
              <div>
                <span>关系上下文</span>
                <strong>
                  {{ traceProcessing.total_relations_found ?? 0 }}
                  →
                  {{ traceProcessing.relations_after_truncation ?? 0 }}
                </strong>
              </div>
              <div>
                <span>文段合并</span>
                <strong>
                  {{ traceProcessing.merged_chunks_count ?? results.length }}
                  →
                  {{ traceProcessing.final_chunks_count ?? results.length }}
                </strong>
              </div>
            </div>

            <div class="trace-keywords">
              <div>
                <h3>Low-level keywords</h3>
                <span
                  v-for="keyword in traceKeywords.low_level || []"
                  :key="`low-${keyword}`"
                >
                  {{ keyword }}
                </span>
                <small v-if="!(traceKeywords.low_level || []).length">无</small>
              </div>
              <div>
                <h3>High-level keywords</h3>
                <span
                  v-for="keyword in traceKeywords.high_level || []"
                  :key="`high-${keyword}`"
                >
                  {{ keyword }}
                </span>
                <small v-if="!(traceKeywords.high_level || []).length">无</small>
              </div>
            </div>

            <div v-if="traceChunkStep" class="trace-chunks">
              <h3>文段来源</h3>
              <article v-for="item in traceChunkStep.items" :key="item.segment_id">
                <div class="trace-chunk-head">
                  <strong>#{{ item.rank }} {{ item.filename }}</strong>
                  <small>{{ item.segment_id }}</small>
                </div>
                <div class="trace-tags">
                  <span
                    v-for="source in item.sources || []"
                    :key="`${item.segment_id}-${source}`"
                  >
                    {{ source }}
                  </span>
                </div>
                <p v-if="item.entities?.length">实体：{{ item.entities.join(" / ") }}</p>
                <p v-if="item.relationships?.length">
                  关系：{{ item.relationships.join(" / ") }}
                </p>
                <p v-if="item.keywords?.length">关键词：{{ item.keywords.join(" / ") }}</p>
              </article>
            </div>
          </div>
        </section>
      </div>

      <aside class="panel upload-sidebar">
        <div class="panel-head">
          <h2>文件上传</h2>
          <div class="actions">
            <button class="icon-button" title="刷新" @click="refreshFiles">
              <RefreshCw :size="18" />
            </button>
            <label class="icon-button" title="上传文件">
              <Upload :size="18" />
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.txt,.md"
                @change="handleUpload"
              />
            </label>
          </div>
        </div>

        <div class="sidebar-sync">
          <span class="sync-state" :class="{ active: syncActive }">{{ formatLastUpdated() }}</span>
        </div>

        <div v-if="uploadQueue.length" class="upload-queue">
          <div v-for="item in uploadQueue" :key="item.name">
            <span>{{ item.name }}</span>
            <span>{{ item.status }}</span>
          </div>
        </div>

        <div class="file-card-list">
          <article v-for="file in files" :key="file.file_id" class="file-card">
            <div class="file-card-head">
              <strong>{{ file.filename }}</strong>
              <span :class="statusClass(file.index_status)">{{ file.index_status }}</span>
            </div>
            <div class="progress" :title="progressText(file)">
              <div :class="progressClass(file)" :style="{ width: `${fileProgress(file)}%` }"></div>
            </div>
            <div class="file-card-meta">
              <span>{{ progressText(file) }}</span>
              <span>片段 {{ file.segment_count ?? "-" }}</span>
            </div>
            <div v-if="file.error_code || file.error_msg" class="file-card-error">
              {{ file.error_code || file.error_msg }}
            </div>
            <div class="row-actions">
              <button class="icon-button" title="图谱" @click="loadGraph(file.file_id)">
                <Activity :size="17" />
              </button>
              <a
                class="icon-button"
                title="下载"
                :href="`${apiBase}/files/${file.file_id}/download`"
                target="_blank"
              >
                <Download :size="17" />
              </a>
              <button class="icon-button danger" title="删除" @click="handleDelete(file.file_id)">
                <Trash2 :size="17" />
              </button>
            </div>
          </article>
          <div v-if="!files.length" class="empty">暂无文件</div>
        </div>
      </aside>
    </section>

    <section v-else class="admin-grid compact-admin">
      <section class="panel task-panel">
        <div class="panel-head">
          <h2>索引任务</h2>
          <div class="actions">
            <button class="icon-button" title="刷新" @click="refreshAdminPage">
              <RefreshCw :size="18" />
            </button>
            <button class="primary" :disabled="loading.trigger" @click="triggerIndex">
              <Play :size="17" /> 执行一次
            </button>
          </div>
        </div>
        <div class="task-summary">
          <div class="task-state">
            <span>当前状态</span>
            <strong>{{ adminRunState }}</strong>
          </div>
          <div>
            <span>待处理</span>
            <strong>{{ pendingCount }}</strong>
          </div>
          <div>
            <span>处理中</span>
            <strong>{{ processingCount }}</strong>
          </div>
          <div>
            <span>失败</span>
            <strong>{{ failedCount }}</strong>
          </div>
        </div>
        <div class="task-details">
          <div>
            <span>下一次自动执行</span>
            <strong>{{ formatTime(nextRunTime) }}</strong>
          </div>
          <div>
            <span>最近任务</span>
            <strong v-if="latestLog">
              {{ latestLog.status }}，处理 {{ latestLog.processed_files }}/{{ latestLog.total_files }}，失败 {{ latestLog.failed_files }}
            </strong>
            <strong v-else>-</strong>
          </div>
        </div>
      </section>

      <section class="panel failure-panel">
        <div class="panel-head">
          <h2>失败处理</h2>
          <span class="subtle">{{ failedFiles.length }} 个待处理</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>文件</th>
                <th>错误</th>
                <th>重试</th>
                <th>下次重试</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="file in failedFiles" :key="file.file_id">
                <td class="name-cell">{{ file.filename }}</td>
                <td class="error-cell">
                  <strong>{{ file.error_code || "-" }}</strong>
                  <span>{{ shortError(file) }}</span>
                </td>
                <td>{{ file.retry_count }}/{{ maxRetries() }}</td>
                <td>{{ formatTime(file.next_retry_at) }}</td>
                <td class="row-actions">
                  <button class="icon-button" title="重试" @click="handleRetry(file.file_id)">
                    <RefreshCw :size="17" />
                  </button>
                  <button class="icon-button danger" title="删除" @click="handleDelete(file.file_id)">
                    <Trash2 :size="17" />
                  </button>
                </td>
              </tr>
              <tr v-if="!failedFiles.length">
                <td colspan="5" class="empty">暂无失败文件</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel sidecar-panel">
        <div class="panel-head">
          <h2>旁路工具</h2>
          <a
            class="primary"
            :href="lightRagWebuiUrl"
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink :size="17" /> 打开 WebUI
          </a>
        </div>
        <div class="sidecar-body">
          <div>
            <span>LightRAG WebUI</span>
            <strong>{{ lightRagWebuiUrl }}</strong>
          </div>
          <p>
            仅用于查看和调试 LightRAG 内部图谱、文档和查询结果；不要在主服务索引时通过该入口写入同一个 working_dir。
          </p>
        </div>
      </section>

      <section class="panel config-panel">
        <div class="panel-head">
          <h2>系统配置</h2>
          <button class="primary" @click="saveConfigs">
            <Settings :size="17" /> 保存
          </button>
        </div>
        <div class="config-grid">
          <label v-for="item in primaryConfigs" :key="item.key">
            <span>{{ item.key }}</span>
            <select v-if="item.value_type === 'enum'" v-model="item.value">
              <option v-for="option in item.enum_values" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
            <input
              v-else-if="item.value_type === 'int'"
              v-model="item.value"
              type="number"
              :min="item.min_value"
              :max="item.max_value"
            />
            <input v-else v-model="item.value" />
            <small>{{ item.description }}；{{ item.effective_scope }}</small>
          </label>
        </div>
      </section>

      <section class="panel diagnostics-panel">
        <details>
          <summary>
            <span>高级诊断</span>
            <Activity :size="18" />
          </summary>
          <div class="diagnostics-grid">
            <div>
              <h3>当前任务</h3>
              <div class="operation-list">
                <div v-for="file in activeFiles" :key="file.file_id">
                  <strong>{{ file.filename }}</strong>
                  <span>{{ file.index_status }} · {{ progressText(file) }}</span>
                </div>
                <div v-if="!activeFiles.length" class="empty compact">暂无执行中的文件</div>
              </div>
            </div>
            <div>
              <h3>调度器</h3>
              <pre>{{ scheduler }}</pre>
            </div>
            <div v-if="advancedConfigs.length">
              <h3>高级配置</h3>
              <div class="config-grid compact">
                <label v-for="item in advancedConfigs" :key="item.key">
                  <span>{{ item.key }}</span>
                  <select v-if="item.value_type === 'enum'" v-model="item.value">
                    <option v-for="option in item.enum_values" :key="option" :value="option">
                      {{ option }}
                    </option>
                  </select>
                  <input
                    v-else-if="item.value_type === 'int'"
                    v-model="item.value"
                    type="number"
                    :min="item.min_value"
                    :max="item.max_value"
                  />
                  <input v-else v-model="item.value" />
                  <small>{{ item.description }}；{{ item.effective_scope }}</small>
                </label>
              </div>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>触发</th>
                  <th>状态</th>
                  <th>处理</th>
                  <th>失败</th>
                  <th>详情</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="log in logs" :key="log.id">
                  <td>{{ formatTime(log.started_at) }}</td>
                  <td>{{ log.trigger_type }}</td>
                  <td><span :class="statusClass(log.status)">{{ log.status }}</span></td>
                  <td>{{ log.processed_files }}/{{ log.total_files }}</td>
                  <td>{{ log.failed_files }}</td>
                  <td class="error-cell">{{ shortDetails(log.details) }}</td>
                </tr>
                <tr v-if="!logs.length">
                  <td colspan="6" class="empty">暂无日志</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </section>
    </section>
  </main>
</template>
