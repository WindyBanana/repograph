"""BPMN 2.0 export of the inferred process flows.

The XML carries diagram interchange (DI) coordinates taken from the same
swimlane layout used for the SVG, so the file opens laid out in bpmn.io, Camunda
Modeler or Signavio rather than as a pile of boxes in one corner.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple
from xml.sax.saxutils import quoteattr

from repograph_core.model import Flow

from .diagrams import flow_diagram
from .layout import Diagram

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
}

_ID = re.compile(r"[^A-Za-z0-9_\-]")


def xid(prefix: str, value: str) -> str:
    cleaned = _ID.sub("_", str(value)).strip("_") or "n"
    return f"{prefix}_{cleaned}"[:120]


def _element_tag(kind: str) -> str:
    return {
        "start": "startEvent",
        "end": "endEvent",
        "decision": "exclusiveGateway",
        "gateway": "exclusiveGateway",
        "subprocess": "subProcess",
        "event": "intermediateCatchEvent",
        "datastore": "dataStoreReference",
        "external": "serviceTask",
        "task": "task",
    }.get(kind, "task")


def export(flow: Flow, diagram: Diagram = None) -> str:
    diagram = diagram or flow_diagram(flow)
    process_id = xid("Process", flow.id)
    collab_id = xid("Collaboration", flow.id)
    participant_id = xid("Participant", flow.id)

    positions: Dict[str, Tuple[float, float, float, float]] = {}
    for node in diagram.nodes:
        w, h = node.w, node.h
        if node.kind in ("start", "end", "event"):
            w = h = 36.0
        elif node.kind in ("decision", "gateway"):
            w = h = 50.0
        positions[node.id] = (node.x, node.y, w, h)

    lanes = diagram.lanes or ["Process"]
    lane_height = diagram.lane_height or 150.0
    nodes_by_lane: Dict[str, List[str]] = {lane: [] for lane in lanes}
    for node in diagram.nodes:
        nodes_by_lane.setdefault(node.group or lanes[0], []).append(node.id)

    flow_nodes = [n for n in diagram.nodes if n.kind != "datastore"]
    stores = [n for n in diagram.nodes if n.kind == "datastore"]
    data_edges = [e for e in diagram.edges if any(s.id == e.target for s in stores)]
    sequence_edges = [e for e in diagram.edges if e not in data_edges]

    out: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    out.append(
        f'<bpmn:definitions xmlns:bpmn="{NS["bpmn"]}" xmlns:bpmndi="{NS["bpmndi"]}" '
        f'xmlns:dc="{NS["dc"]}" xmlns:di="{NS["di"]}" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'id="Definitions_{xid("d", flow.id)}" targetNamespace="http://repograph.dev/bpmn" '
        f'exporter="repograph" exporterVersion="0.1">'
    )
    out.append(f'  <bpmn:collaboration id="{collab_id}">')
    out.append(f'    <bpmn:participant id="{participant_id}" name={quoteattr(flow.name)} '
               f'processRef="{process_id}" />')
    out.append("  </bpmn:collaboration>")
    out.append(f'  <bpmn:process id="{process_id}" isExecutable="false">')

    out.append(f'    <bpmn:laneSet id="{xid("LaneSet", flow.id)}">')
    for lane in lanes:
        lane_id = xid("Lane", f"{flow.id}_{lane}")
        out.append(f'      <bpmn:lane id="{lane_id}" name={quoteattr(lane)}>')
        for node_id in nodes_by_lane.get(lane, []):
            out.append(f"        <bpmn:flowNodeRef>{xid('N', node_id)}</bpmn:flowNodeRef>")
        out.append("      </bpmn:lane>")
    out.append("    </bpmn:laneSet>")

    incoming: Dict[str, List[str]] = {}
    outgoing: Dict[str, List[str]] = {}
    for index, edge in enumerate(sequence_edges):
        edge_id = xid("Flow", f"{flow.id}_{index}")
        outgoing.setdefault(edge.source, []).append(edge_id)
        incoming.setdefault(edge.target, []).append(edge_id)

    for node in flow_nodes:
        tag = _element_tag(node.kind)
        node_id = xid("N", node.id)
        out.append(f"    <bpmn:{tag} id=\"{node_id}\" name={quoteattr(node.label)}>")
        for edge_id in incoming.get(node.id, []):
            out.append(f"      <bpmn:incoming>{edge_id}</bpmn:incoming>")
        for edge_id in outgoing.get(node.id, []):
            out.append(f"      <bpmn:outgoing>{edge_id}</bpmn:outgoing>")
        for index, edge in enumerate(data_edges):
            if edge.source == node.id:
                assoc = xid("DataOut", f"{flow.id}_{index}")
                out.append(f'      <bpmn:dataOutputAssociation id="{assoc}">')
                out.append(f"        <bpmn:targetRef>{xid('N', edge.target)}</bpmn:targetRef>")
                out.append("      </bpmn:dataOutputAssociation>")
        out.append(f"    </bpmn:{tag}>")

    for store in stores:
        out.append(f'    <bpmn:dataStoreReference id="{xid("N", store.id)}" '
                   f"name={quoteattr(store.label)} />")

    for index, edge in enumerate(sequence_edges):
        edge_id = xid("Flow", f"{flow.id}_{index}")
        name = f" name={quoteattr(edge.label)}" if edge.label else ""
        out.append(f'    <bpmn:sequenceFlow id="{edge_id}" sourceRef="{xid("N", edge.source)}" '
                   f'targetRef="{xid("N", edge.target)}"{name} />')
    out.append("  </bpmn:process>")

    # ------------------------------------------------------------------ DI
    out.append("  <bpmndi:BPMNDiagram id=\"Diagram\">")
    out.append(f'    <bpmndi:BPMNPlane id="Plane" bpmnElement="{collab_id}">')
    total_w = max(diagram.width, 600)
    total_h = max(len(lanes) * lane_height + 40, 200)
    out.append(f'      <bpmndi:BPMNShape id="Shape_{participant_id}" bpmnElement="{participant_id}" '
               f'isHorizontal="true">')
    out.append(f'        <dc:Bounds x="20" y="20" width="{total_w:.0f}" height="{total_h:.0f}" />')
    out.append("      </bpmndi:BPMNShape>")
    for index, lane in enumerate(lanes):
        lane_id = xid("Lane", f"{flow.id}_{lane}")
        out.append(f'      <bpmndi:BPMNShape id="Shape_{lane_id}" bpmnElement="{lane_id}" '
                   f'isHorizontal="true">')
        out.append(f'        <dc:Bounds x="50" y="{20 + index * lane_height:.0f}" '
                   f'width="{total_w - 30:.0f}" height="{lane_height:.0f}" />')
        out.append("      </bpmndi:BPMNShape>")
    for node in diagram.nodes:
        x, y, w, h = positions[node.id]
        node_id = xid("N", node.id)
        out.append(f'      <bpmndi:BPMNShape id="Shape_{node_id}" bpmnElement="{node_id}">')
        out.append(f'        <dc:Bounds x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" />')
        out.append("      </bpmndi:BPMNShape>")
    for index, edge in enumerate(sequence_edges):
        edge_id = xid("Flow", f"{flow.id}_{index}")
        points = edge.points or _fallback_points(positions, edge.source, edge.target)
        out.append(f'      <bpmndi:BPMNEdge id="Edge_{edge_id}" bpmnElement="{edge_id}">')
        for px, py in points:
            out.append(f'        <di:waypoint x="{px:.0f}" y="{py:.0f}" />')
        out.append("      </bpmndi:BPMNEdge>")
    for index, edge in enumerate(data_edges):
        assoc = xid("DataOut", f"{flow.id}_{index}")
        points = edge.points or _fallback_points(positions, edge.source, edge.target)
        out.append(f'      <bpmndi:BPMNEdge id="Edge_{assoc}" bpmnElement="{assoc}">')
        for px, py in points:
            out.append(f'        <di:waypoint x="{px:.0f}" y="{py:.0f}" />')
        out.append("      </bpmndi:BPMNEdge>")
    out.append("    </bpmndi:BPMNPlane>")
    out.append("  </bpmndi:BPMNDiagram>")
    out.append("</bpmn:definitions>")
    return "\n".join(out)


def _fallback_points(positions: Dict[str, Tuple[float, float, float, float]],
                     source: str, target: str) -> List[Tuple[float, float]]:
    sx, sy, sw, sh = positions.get(source, (0, 0, 100, 60))
    tx, ty, tw, th = positions.get(target, (200, 0, 100, 60))
    return [(sx + sw, sy + sh / 2), (tx, ty + th / 2)]


def build_all(flows, max_flows: int = 14) -> Dict[str, str]:
    return {f"flow-{flow.id}": export(flow) for flow in list(flows)[:max_flows]}
