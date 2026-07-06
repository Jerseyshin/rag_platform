<script setup>
import {
  Activity,
  Download,
  FileText,
  Play,
  RefreshCw,
  Search,
  Settings,
  Trash2,
  Upload,
} from "@lucide/vue";
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import {
  adminConfigs,
  adminStatus,
  apiBase,
  deleteFile,
  listFiles,
  retrieve,
  schedulerLogs,
  schedulerStatus,
  triggerScheduler,
  updateConfigs,
  uploadFile,
} from "./api";

const tab = ref("workspace");
const files = ref([]);
const results = ref([]);
const uploadQueue = ref([]);
const status = ref(null);
const configs = ref([]);
const scheduler = ref(null);
const logs = ref([]);
const message = ref("");
const pollTimer = ref(null);
const pollingStarting = ref(false);
const loading = reactive({
  files: false,
  upload: false,
  retrieve: false,
  admin: false,
  trigger: false,
});

const query = reactive({
  query: "",
  top_k: 5,
  threshold: 0.7,
});

const editableConfigs = computed(() =>
  configs.value.filter((item) =>
    [
      "rag.chunk_size",
      "rag.chunk_overlap",
      "rag.default_top_k",
      "rag.default_threshold",
      "rag.search_mode",
      "rag.llm_model",
      "scheduler.interval_minutes",
      "scheduler.batch_size",
      "scheduler.max_retries",
      "scheduler.retry_interval_minutes",
      "scheduler.processing_timeout_minutes",
    ].includes(item.key),
  ),
);

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
}

async function refreshFiles() {
  loading.files = true;
  try {
    const payload = await listFiles();
    files.value = payload.items;
    if (hasActiveFiles() && !pollTimer.value && !pollingStarting.value) {
      startFileStatusPolling();
    }
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
    if (hasActiveFiles()) {
      startFileStatusPolling();
    }
  } finally {
    loading.upload = false;
    event.target.value = "";
  }
}

async function handleDelete(fileId) {
  try {
    await deleteFile(fileId);
    await refreshFiles();
    if (hasActiveFiles()) {
      startFileStatusPolling();
    }
  } catch (error) {
    setMessage(`删除失败：${error.message}`);
  }
}

async function runRetrieve() {
  if (!query.query.trim()) return;
  loading.retrieve = true;
  try {
    results.value = (await retrieve({
      query: query.query.trim(),
      top_k: query.top_k || undefined,
      threshold: query.threshold,
    })).chunks;
  } finally {
    loading.retrieve = false;
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
  } catch (error) {
    setMessage(`刷新管理信息失败：${error.message}`);
  } finally {
    loading.admin = false;
  }
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

function startFileStatusPolling({ includeAdmin = false } = {}) {
  clearPolling();
  pollingStarting.value = true;
  let tick = 0;
  const maxTicks = 40;

  const refresh = async () => {
    tick += 1;
    if (includeAdmin) {
      await Promise.all([refreshFiles(), refreshAdmin()]);
    } else {
      await refreshFiles();
    }
    if (!hasActiveFiles() || tick >= maxTicks) {
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
      <section class="panel files-panel">
        <div class="panel-head">
          <h2>文件</h2>
          <div class="actions">
            <label class="icon-button" title="上传文件">
              <Upload :size="18" />
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.txt,.md"
                @change="handleUpload"
              />
            </label>
            <button class="icon-button" title="刷新" @click="refreshFiles">
              <RefreshCw :size="18" />
            </button>
          </div>
        </div>

        <div v-if="uploadQueue.length" class="upload-queue">
          <div v-for="item in uploadQueue" :key="item.name">
            <span>{{ item.name }}</span>
            <span>{{ item.status }}</span>
          </div>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>文件名</th>
                <th>状态</th>
                <th>进度</th>
                <th>片段</th>
                <th>错误</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="file in files" :key="file.file_id">
                <td class="name-cell">{{ file.filename }}</td>
                <td><span :class="statusClass(file.index_status)">{{ file.index_status }}</span></td>
                <td>
                  <div class="progress" :title="progressText(file)">
                    <div :class="progressClass(file)" :style="{ width: `${fileProgress(file)}%` }"></div>
                  </div>
                  <div class="progress-label">{{ progressText(file) }}</div>
                </td>
                <td>{{ file.segment_count ?? "-" }}</td>
                <td class="error-cell">{{ file.error_code || file.error_msg || "-" }}</td>
                <td class="row-actions">
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
                </td>
              </tr>
              <tr v-if="!files.length">
                <td colspan="6" class="empty">暂无文件</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

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
          <label>阈值 <input v-model.number="query.threshold" type="number" min="0" max="1" step="0.05" /></label>
        </div>
        <div class="results">
          <article v-for="item in results" :key="item.segment_id" class="result-item">
            <div class="result-meta">
              <span>#{{ item.rank }}</span>
              <span>{{ item.score.toFixed(3) }}</span>
              <span>{{ item.citation.filename }}</span>
              <span>{{ item.citation.location_type }} {{ item.citation.location }}</span>
            </div>
            <p>{{ item.content }}</p>
            <a :href="`${apiBase}${item.citation.download_url}`" target="_blank">下载原文</a>
          </article>
          <div v-if="!results.length" class="empty">暂无检索结果</div>
        </div>
      </section>
    </section>

    <section v-else class="admin-grid">
      <section class="panel">
        <div class="panel-head">
          <h2>系统状态</h2>
          <button class="icon-button" title="刷新" @click="refreshAdmin">
            <RefreshCw :size="18" />
          </button>
        </div>
        <div class="metrics">
          <div>
            <span>文件</span>
            <strong>{{ status?.files?.completed || 0 }}/{{ Object.values(status?.files || {}).reduce((a, b) => a + b, 0) }}</strong>
          </div>
          <div>
            <span>片段</span>
            <strong>{{ status?.segments?.indexed || 0 }}</strong>
          </div>
          <div>
            <span>调度</span>
            <strong>{{ scheduler?.running ? "运行中" : "未运行" }}</strong>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>调度</h2>
          <button class="primary" :disabled="loading.trigger" @click="triggerIndex">
            <Play :size="17" /> 执行一次
          </button>
        </div>
        <pre>{{ scheduler }}</pre>
      </section>

      <section class="panel config-panel">
        <div class="panel-head">
          <h2>配置</h2>
          <button class="primary" @click="saveConfigs">
            <Settings :size="17" /> 保存
          </button>
        </div>
        <div class="config-grid">
          <label v-for="item in editableConfigs" :key="item.key">
            <span>{{ item.key }}</span>
            <input v-model="item.value" />
          </label>
        </div>
      </section>

      <section class="panel logs-panel">
        <div class="panel-head">
          <h2>任务日志</h2>
          <Activity :size="18" />
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
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in logs" :key="log.id">
                <td>{{ new Date(log.started_at).toLocaleString() }}</td>
                <td>{{ log.trigger_type }}</td>
                <td><span :class="statusClass(log.status)">{{ log.status }}</span></td>
                <td>{{ log.processed_files }}/{{ log.total_files }}</td>
                <td>{{ log.failed_files }}</td>
              </tr>
              <tr v-if="!logs.length">
                <td colspan="5" class="empty">暂无日志</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>
  </main>
</template>
