"""Software Bill of Materials generation (CycloneDX 1.5 and SPDX 2.3, JSON)."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from ..model import Dependency, Finding, ScanResult


def _ref(dep: Dependency) -> str:
    return dep.purl or f"pkg:generic/{dep.name}@{dep.version}" if dep.version else f"pkg:generic/{dep.name}"


def cyclonedx(result: ScanResult) -> Dict[str, Any]:
    components: List[Dict[str, Any]] = []
    vulns_by_package: Dict[str, List[Finding]] = {}
    for finding in result.findings:
        if finding.category == "dependency" and finding.identifier.startswith(("CVE", "GHSA", "OSV", "PYSEC", "GO-")):
            vulns_by_package.setdefault(finding.package, []).append(finding)

    for dep in result.dependencies:
        component: Dict[str, Any] = {
            "type": "library",
            "bom-ref": _ref(dep),
            "name": dep.name,
            "version": dep.version or "unknown",
            "purl": dep.purl or "",
            "scope": "required" if dep.scope == "runtime" else "optional",
            "properties": [
                {"name": "repograph:ecosystem", "value": dep.ecosystem},
                {"name": "repograph:direct", "value": str(dep.direct).lower()},
                {"name": "repograph:used", "value": str(dep.used).lower()},
                {"name": "repograph:declaredIn", "value": ", ".join(dep.declared_in[:4])},
            ],
        }
        if dep.license:
            component["licenses"] = [{"license": {"name": dep.license}}]
        components.append(component)

    vulnerabilities = []
    for package, findings in sorted(vulns_by_package.items()):
        for finding in findings:
            vulnerabilities.append({
                "bom-ref": finding.id,
                "id": finding.identifier or finding.id,
                "description": finding.title,
                "ratings": [{"severity": finding.severity}],
                "cwes": [int(c.split("-")[1]) for c in finding.cwe.split(",") if c.strip().startswith("CWE-")
                         and c.split("-")[1].strip().isdigit()],
                "recommendation": finding.remediation,
                "affects": [{"ref": next((_ref(d) for d in result.dependencies if d.name == package), package)}],
                "advisories": [{"url": url} for url in finding.references if url],
            })

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:" + _stable_uuid(result.meta.repo_name + result.meta.generated_at),
        "version": 1,
        "metadata": {
            "timestamp": result.meta.generated_at,
            "tools": [{"vendor": "repograph", "name": "repograph", "version": result.meta.version}],
            "component": {
                "type": "application",
                "bom-ref": f"root-{result.meta.repo_name}",
                "name": result.meta.repo_name,
                "version": result.git.head[:12] if result.git.head else "0.0.0",
            },
        },
        "components": components,
        "vulnerabilities": vulnerabilities,
    }


def spdx(result: ScanResult) -> Dict[str, Any]:
    packages = [{
        "SPDXID": "SPDXRef-Package-root",
        "name": result.meta.repo_name,
        "downloadLocation": result.git.remote or "NOASSERTION",
        "filesAnalyzed": False,
        "versionInfo": result.git.head[:12] if result.git.head else "NOASSERTION",
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
    }]
    relationships = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relatedSpdxElement": "SPDXRef-Package-root",
        "relationshipType": "DESCRIBES",
    }]
    for index, dep in enumerate(result.dependencies):
        spdx_id = f"SPDXRef-Package-{index}"
        packages.append({
            "SPDXID": spdx_id,
            "name": dep.name,
            "versionInfo": dep.version or "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": dep.license or "NOASSERTION",
            "licenseDeclared": dep.license or "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "externalRefs": ([{
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": dep.purl,
            }] if dep.purl else []),
        })
        relationships.append({
            "spdxElementId": "SPDXRef-Package-root",
            "relatedSpdxElement": spdx_id,
            "relationshipType": "DEPENDS_ON",
        })
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{result.meta.repo_name}-sbom",
        "documentNamespace": f"https://repograph.dev/spdx/{_stable_uuid(result.meta.repo_name)}",
        "creationInfo": {
            "created": result.meta.generated_at,
            "creators": [f"Tool: repograph-{result.meta.version}"],
        },
        "packages": packages,
        "relationships": relationships,
    }


def _stable_uuid(seed: str) -> str:
    digest = hashlib.sha1(seed.encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"
