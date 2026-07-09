<template>
  <div v-if="graphData">
    <VNetworkGraph
      ref="networkGraph"
      :configs="configs"
      :edges="graphData.edges"
      :event-handlers="eventHandlers"
      :layouts="graphData.layouts"
      :nodes="graphData.nodes"
      :style="{ height: graphHeight + 'px' }"
    >
      <template #edge-label="{ edge, hovered, ...slotProps }">
        <VEdgeLabel
          v-if="hovered"
          align="center"
          :text="edge.kind"
          vertical-align="above"
          v-bind="slotProps"
        />
      </template>
    </VNetworkGraph>

    <div class="flex flex-wrap gap-4 mt-2 text-xs opacity-70">
      <span class="flex items-center gap-1">
        <svg
          height="10"
          width="10"
        ><circle
          cx="5"
          cy="5"
          :fill="colors.center"
          r="5"
        /></svg>
        This item
      </span>

      <span class="flex items-center gap-1">
        <svg
          height="10"
          width="10"
        ><circle
          cx="5"
          cy="5"
          :fill="colors.known"
          r="5"
        /></svg>
        In the meta-register
      </span>

      <span class="flex items-center gap-1">
        <svg
          height="10"
          width="10"
        ><circle
          cx="5"
          cy="5"
          :fill="colors.unknown"
          r="5"
          stroke="#666"
          stroke-dasharray="2"
        /></svg>
        Outside the meta-register
      </span>
    </div>
  </div>

  <p
    v-else
    class="opacity-70 text-sm"
  >
    No dependency relationships found.
  </p>
</template>

<script lang="ts" setup>
import type { DependencyGraph } from '~/types/api';
import dagre from 'dagre';
import { VEdgeLabel, VNetworkGraph } from 'v-network-graph';
import 'v-network-graph/lib/style.css';

const props = withDefaults(defineProps<{
  graph: DependencyGraph | null | undefined;
  centerId: string;
  nodeType: 'bblock' | 'register';
  nodeSize?: number;
  height?: number;
}>(), {
  nodeSize: 32,
  height: 360,
});

const router = useRouter();
const theme = useTheme();
const labelColor = computed(() => theme.current.value.dark ? '#e0e0e0' : '#1a1a1a');
const networkGraph = ref<InstanceType<typeof VNetworkGraph> | null>(null);

const colors = {
  center: '#7c3aed',
  known: '#2f9e44',
  unknown: '#888',
};

const edgeColors: Record<string, string> = {
  dependsOn: '#aaa',
  isProfileOf: '#4a90d9',
};

function linkFor(nodeId: string, registerId: string | null): string | null {
  if (!registerId) {
    return null;
  }
  const [org, register] = registerId.split('/');
  return props.nodeType === 'bblock' ? `/orgs/${org}/registers/${register}/bblocks/${nodeId}` : `/orgs/${org}/registers/${register}`;
}

interface LayoutNode {
  name: string;
  color: string;
  dashed: boolean;
  known: boolean;
  registerId: string | null;
}

const graphData = computed(() => {
  const graph = props.graph;
  if (!graph || graph.edges.length === 0) {
    return null;
  }

  const nodes: Record<string, LayoutNode> = {};
  const edges: Record<string, { source: string; target: string; kind: string }> = {};
  const layoutNodes: Record<string, { x: number; y: number }> = {};

  const dg = new dagre.graphlib.Graph();
  dg.setGraph({ rankdir: 'LR', nodesep: props.nodeSize, edgesep: props.nodeSize, ranksep: props.nodeSize * 2.5 });
  dg.setDefaultEdgeLabel(() => ({}));

  for (const node of graph.nodes) {
    const isCenter = node.id === props.centerId;
    nodes[node.id] = {
      name: node.name,
      color: isCenter ? colors.center : (node.known ? colors.known : colors.unknown),
      dashed: !node.known,
      known: node.known,
      registerId: node.register_id,
    };
    dg.setNode(node.id, {
      label: node.name,
      width: Math.max(props.nodeSize, node.name.length * 5.2),
      height: props.nodeSize + 12,
    });
  }

  for (const edge of graph.edges) {
    const edgeId = `${edge.source}-${edge.target}-${edge.kind}`;
    if (!edges[edgeId]) {
      edges[edgeId] = { source: edge.source, target: edge.target, kind: edge.kind };
      dg.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(dg);
  for (const nodeId of dg.nodes() as string[]) {
    const dgNode = dg.node(nodeId);
    if (dgNode) {
      layoutNodes[nodeId] = { x: dgNode.x, y: dgNode.y };
    }
  }

  return { nodes, edges, layouts: { nodes: layoutNodes } };
});

const graphHeight = computed(() => {
  const nodes = graphData.value?.layouts?.nodes;
  if (!nodes) {
    return props.height;
  }
  const ys = Object.values(nodes).map(n => n.y);
  if (ys.length === 0) {
    return props.height;
  }
  const ySpan = Math.max(...ys) - Math.min(...ys);
  return Math.min(props.height, Math.max(160, ySpan + props.nodeSize * 4));
});

const configs = computed(() => ({
  view: {
    autoPanAndZoomOnLoad: 'fit-content' as const,
    scalingObjects: false,
  },
  node: {
    normal: {
      radius: props.nodeSize / 2,
      color: (node: LayoutNode) => node.color,
      strokeWidth: (node: LayoutNode) => (node.dashed ? 1 : 0),
      strokeColor: '#555',
      strokeDasharray: (node: LayoutNode) => (node.dashed ? '3' : '0'),
    },
    hover: {
      color: (node: LayoutNode) => node.color,
    },
    label: {
      directionAutoAdjustment: true,
      color: labelColor.value,
    },
  },
  edge: {
    normal: {
      color: (edge: { kind: string }) => edgeColors[edge.kind] ?? '#aaa',
      width: 2,
    },
    hover: {
      color: (edge: { kind: string }) => edgeColors[edge.kind] ?? '#aaa',
    },
    margin: 4,
    marker: {
      target: { type: 'arrow' as const },
    },
    label: {
      fontSize: 9,
      color: labelColor.value,
    },
  },
}));

const eventHandlers = {
  'node:click': ({ node }: { node: string }) => {
    const data = graphData.value?.nodes?.[node];
    if (!data?.known) {
      return;
    }
    const target = linkFor(node, data.registerId);
    if (target) {
      router.push(target);
    }
  },
  'node:pointerover': ({ node, event }: { node: string; event: PointerEvent }) => {
    const data = graphData.value?.nodes?.[node];
    const svg = (event.target as SVGElement)?.ownerSVGElement;
    if (svg) {
      svg.style.cursor = data?.known ? 'pointer' : 'default';
    }
  },
};

watch(graphData, (v) => {
  if (v && networkGraph.value) {
    networkGraph.value.fitToContents();
  }
});
</script>
