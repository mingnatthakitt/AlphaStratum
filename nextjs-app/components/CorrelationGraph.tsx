"use client";

import { useEffect, useRef } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { drag, type D3DragEvent } from "d3-drag";
import { select } from "d3-selection";
import { cssColor } from "@/lib/chartColors";

interface GraphNode extends SimulationNodeDatum {
  id: string;
  name?: string;
}

interface GraphEdge extends SimulationLinkDatum<GraphNode> {
  weight: number;
}

interface Props {
  nodes: { id: string; name: string }[];
  edges: { source: string; target: string; weight: number }[];
}

export default function CorrelationGraph({ nodes, edges }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const width = svgRef.current.clientWidth || 800;
    const height = 500;
    const textColor = cssColor("--foreground", "#0f172a");

    const typedNodes: GraphNode[] = nodes.map((n) => ({ ...n }));
    const typedEdges: GraphEdge[] = edges.map((e) => ({ ...e }));

    select(svgRef.current).selectAll("*").remove();

    const svg = select(svgRef.current)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img")
      .attr("aria-label", "Correlation network graph of sector tickers");

    const simulation = forceSimulation(typedNodes)
      .force(
        "link",
        forceLink<GraphNode, GraphEdge>(typedEdges)
          .id((d) => d.id)
          .distance(80),
      )
      .force("charge", forceManyBody().strength(-200))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collision", forceCollide<GraphNode>().radius(30));

    const link = svg
      .append("g")
      .selectAll<SVGLineElement, GraphEdge>("line")
      .data(typedEdges)
      .join("line")
      .attr("stroke", "#94a3b8")
      .attr("stroke-opacity", (d) => Math.min(1, Math.abs(d.weight)))
      .attr("stroke-width", (d) => Math.abs(d.weight) * 3);

    const onDragStart = (event: D3DragEvent<SVGGElement, GraphNode, unknown>, d: GraphNode) => {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    };
    const onDrag = (event: D3DragEvent<SVGGElement, GraphNode, unknown>, d: GraphNode) => {
      d.fx = event.x;
      d.fy = event.y;
    };
    const onDragEnd = (event: D3DragEvent<SVGGElement, GraphNode, unknown>, d: GraphNode) => {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    };

    const node = svg
      .append("g")
      .selectAll<SVGGElement, GraphNode>("g")
      .data(typedNodes)
      .join("g")
      .call(drag<SVGGElement, GraphNode>().on("start", onDragStart).on("drag", onDrag).on("end", onDragEnd));

    node
      .append("circle")
      .attr("r", 8)
      .attr("fill", "#3b82f6")
      .attr("stroke", textColor)
      .attr("stroke-width", 2);

    node
      .append("text")
      .text((d) => d.id)
      .attr("x", 12)
      .attr("y", 4)
      .attr("font-size", "11px")
      .attr("fill", textColor);

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as GraphNode).x ?? 0)
        .attr("y1", (d) => (d.source as GraphNode).y ?? 0)
        .attr("x2", (d) => (d.target as GraphNode).x ?? 0)
        .attr("y2", (d) => (d.target as GraphNode).y ?? 0);
      node.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Re-centre the layout when the container resizes. The width was sampled
    // once at mount, so the graph previously never reflowed.
    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const nextWidth = entry.contentRect.width;
      if (!nextWidth) return;
      svg.attr("width", nextWidth).attr("viewBox", `0 0 ${nextWidth} ${height}`);
      simulation.force("center", forceCenter(nextWidth / 2, height / 2));
      simulation.alpha(0.3).restart();
    });
    resizeObserver.observe(svgRef.current);

    return () => {
      resizeObserver.disconnect();
      simulation.stop();
      // d3-drag installs window-level mousemove/mouseup handlers; without this
      // they survive an interrupted drag and leak one set per unmount.
      node.on(".drag", null);
    };
  }, [nodes, edges]);

  return (
    <div>
      <svg ref={svgRef} className="w-full h-[500px]" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        Minimum spanning tree from 60-day return correlations · Drag nodes to explore
      </p>
    </div>
  );
}
