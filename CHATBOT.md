# SI Assistant — Standards & Interoperability AI Chatbot

An AI-powered chatbot providing trusted, context-aware support for countries implementing digital health standards and interoperability infrastructure.

---

## Core Concept

The SI Assistant delivers **just-in-time, evidence-based guidance** through a conversational interface grounded in a curated knowledge base of public literature from WHO, World Bank, ADB, ITU, UNICEF, HL7, OpenHIE, and other international agencies.

Unlike a general-purpose AI, every answer is retrieved from vetted source documents — not generated from training data. This means responses are traceable, grounded, and aligned with internationally recognised guidance.

> "Countries are under increasing pressure to adopt digital health standards like FHIR and SNOMED, but lack expert support. The SI Assistant bridges that gap — on demand, in plain language, at any stage of implementation."

---

## Key Capabilities

- Answers questions on FHIR, HL7, IHE, SNOMED, ICD-11, LOINC, and other health data standards
- Supports national digital health strategy, architecture design, and roadmap planning
- Guides interoperability governance, policy, and stakeholder alignment
- Assists with system integration planning (EMR, DHIS2, national registries, CRVS)
- Supports interoperability maturity assessment and readiness evaluation
- Tailors responses by role — policy maker, technical implementer, clinician, or researcher
- Cites source documents inline so every answer is verifiable
- Prioritises field-validated implementation experience from the SSCP project where available

---

## Who Can Benefit

**For Ministries of Health and Policy Makers**
- Plain-language answers on governance, strategy, and investment decisions
- Guidance on national digital health legislation and data protection frameworks
- Support for drafting phased implementation roadmaps

**For Technical Implementers and Development Partners**
- Standards selection guidance (FHIR, HL7 v2, IHE profiles, OpenHIE)
- Architecture recommendations for national health information exchanges
- Practical integration approaches for DHIS2, EMRs, and national registries

**For Clinicians and Health Workers**
- Accessible explanations of how standards affect clinical workflows
- Guidance on terminology (ICD-11, SNOMED CT, LOINC) in clinical context

**For Researchers, Trainers, and CoP Leads**
- Self-paced learning resource on interoperability concepts and frameworks
- Reference tool for capacity-building workshops and connectathons

---

## Example Questions

The following are drawn from real questions submitted by users during the design phase:

- *How can we ensure our FHIR implementation is compliant with our country's Personal Data Protection Law?*
- *What is a realistic interoperability roadmap for a hospital with a legacy HIS?*
- *What governance structures are needed before launching a national health information exchange?*
- *Can you help map our existing health indicators to ICD-11 or LOINC?*
- *What are the minimum requirements for FHIR-based interoperability in a low-resource setting?*
- *How do we align existing health IT systems with our national enterprise architecture?*
- *What reference architecture is recommended for a national HIE in a Pacific Island country?*
- *Can you evaluate our country's current interoperability maturity level?*

---

## Knowledge Base

The chatbot is grounded in two tiers of curated content:

**General Knowledge Base** — publicly available guidance from:
WHO, World Bank, ADB, ITU, UNICEF, CSIRO, HL7, OpenHIE, IHE, AeHIN, and other international digital health bodies. Includes implementation guides, strategy documents, assessment toolkits, technical handbooks, and a domain glossary of 80+ interoperability terms and synonyms.

**SSCP Priority Sources** — primary materials from the Standards and Interoperability for Country Capacity Project (SSCP), including field learnings, country assessments, lessons learned, and real implementation experience from Pacific Island countries and other LMICs. These sources are treated as the primary authoritative basis for implementation-level answers.

All content is publicly licensed and attributed. No proprietary data is used.

---

## Phased Development Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **Phase 1 — Agentic Learning** | RAG chatbot with curated KB, role-based personas, source citation, SSCP priority retrieval, evaluation benchmark | Active |
| **Phase 2 — Problem Solving** | Structured decision-support workflows, WHO SMART Guidelines integration, FHIR IG testing and validation support | Planned |
| **Phase 3 — Innovation** | MCP-powered FHIR design pattern generation, multilingual support, offline/low-resource environments, AI trainer module | Future |

---

## Ethics and Responsible AI

- Grounded exclusively in publicly available, licensed, and attributed source documents
- Inline citations on every response — no answer without a traceable source
- Clear distinction between published guidance and interpretation
- Human-in-the-loop feedback mechanism built into the interface
- Hallucination prevention: the assistant explicitly states when a topic is not covered in the knowledge base rather than fabricating an answer
- Role-aware responses that match the user's context and decision-making needs

---

## Access

The SI Assistant is currently available to authorised users via a secure web interface. Access is role-based (admin and standard user). Contact the SSCP team to request access or to discuss deployment for your organisation.

For technical teams interested in deploying their own instance, the full source code, ingestion pipeline, knowledge base structure, and deployment guide are available in this repository.

---

## Built With

[Streamlit](https://streamlit.io) · [LiteLLM](https://github.com/BerriAI/litellm) · [ChromaDB](https://www.trychroma.com) · [sentence-transformers](https://www.sbert.net) · [Claude (Anthropic)](https://www.anthropic.com) · Python

Knowledge base hosted on AWS S3 · Deployed on AWS EC2 · Vector search via ChromaDB on EBS
