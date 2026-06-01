# Digital Health Standards and Interoperability — Glossary

Source: WHO Classification of Digital Interventions, Services and Applications in Health (CDISAH v2.0, 2023) and domain practice.

This glossary defines terminology equivalences used in digital health interoperability. When a term appears in a question or document, treat all listed equivalents as referring to the same concept.

---

## SECTION 1 — Domain-Specific Equivalences

These are terms that mean the same thing but appear under different names across countries, agencies, and projects.

HIE / Health Information Exchange / National DPI-H / Digital Public Infrastructure for Health / interoperability layer / health data exchange layer / data interchange layer — A national platform that facilitates communication and data exchange between different health information systems, eHealth services, care organisations, governmental agencies, and patient communities. The WHO CDISAH defines this as D2 (Data interchange and interoperability) and it is synonymous with the interoperability layer concept.

ILR / Client Registry / Master Patient Index / MPI / person-centred registry / patient registry / unique patient identifier system — A central authority that manages the unique identity of individuals receiving health services within a country. WHO code C8. Enables matching of a person across multiple systems.

SHR / Shared Health Record / Longitudinal Health Record / Clinical Data Repository / National Health Domain-Specific Registry / Clinical Data Warehouse — A repository containing normalised, person-centric health records validated against registries. WHO code D8. Contains the longitudinal view of a patient's health history across facilities and programs.

OpenHIE / Open Health Information Exchange / HIE reference architecture / health information mediator / interoperability architecture framework — An open architecture framework defining how health information exchange should be structured using registries, a shared health record, and an interoperability layer. OpenHIE components map directly to WHO CDISAH categories C, D, and A.

FHIR IG / Implementation Guide / FHIR Profile / IG / implementation specification — A set of rules and constraints on FHIR resources that describe how FHIR should be implemented for a specific use case, country, or domain. FHIR IGs define the technical requirements for interoperability.

DPI / Digital Public Infrastructure / digital health infrastructure / national digital health platform — Foundational digital systems that are shared, open, and interoperable across government services. In health, DPI-H refers specifically to the health components including HIE, client registry, facility registry, and terminology services.

EMR / EHR / Electronic Medical Record / Electronic Health Record / clinical information system / point of care system — A secure system holding information about people's health and clinical care managed by healthcare providers. WHO code A5. EMR and EHR are used interchangeably.

HMIS / Health Management Information System / health information system / aggregate data system / national health reporting system — Stores routinely collected aggregate healthcare data and facilitates analysis to improve health service quality. WHO code D6. DHIS2 is the most widely deployed HMIS platform in low and middle income countries.

---

## SECTION 2 — Core Framework Terms

CDISAH — Classification of Digital Interventions, Services and Applications in Health. The WHO taxonomy (second edition, 2023) that provides a shared language to describe uses of digital technology for health. Organised across three axes: Digital Health Interventions, Health System Challenges, and Services and Application Types. Predecessor was CDHI (v1.0, 2018).

DHI — Digital Health Intervention. A discrete technology functionality designed to achieve a specific objective addressing a health system challenge. The fundamental unit of analysis in the CDISAH taxonomy.

Digital Health — The systematic application of information and communications technologies, computer science, and data to support informed decision-making by individuals, the health workforce, and health systems. Umbrella term encompassing eHealth and mHealth.

eHealth — Electronic Health. Use of information and communications technology for health. Predecessor and related term to digital health. Used interchangeably in some contexts.

mHealth — Mobile Health. Use of mobile and wireless technologies to support the achievement of health objectives. A subset of digital health.

HSC — Health System Challenge. A generic standardised description of a need or gap that reduces optimal health service implementation. Nine categories: Information, Availability, Quality, Acceptability, Utilization, Efficiency, Cost, Accountability, Equity.

Digital Health Enterprise Architecture — The architectural blueprint describing how digital health services and applications are structured and interconnected within a health system.

---

## SECTION 3 — Interoperability and Data Standards

FHIR — Fast Healthcare Interoperability Resources. The HL7 standard for exchanging health information electronically. Uses RESTful APIs and structured data resources. Current version R4 is most widely implemented. R5 is the latest.

HL7 — Health Level Seven. The standards development organisation that produces FHIR and other health informatics standards including HL7 v2 messaging and CDA documents.

SNOMED CT — Systematized Nomenclature of Medicine Clinical Terms. A comprehensive, multilingual clinical terminology providing a standardised way to represent healthcare concepts in electronic health systems. Maps to ICD-10/11 for reporting.

LOINC — Logical Observation Identifiers Names and Codes. A universal standard for identifying medical laboratory observations, clinical measurements, and other health measurements.

ICD — International Classification of Diseases. The WHO international standard for reporting diseases, conditions, and causes of death. Current versions: ICD-10 (widely used), ICD-11 (being adopted).

ICPC2 — International Classification of Primary Care version 2. Coding standard used in primary care settings.

Semantic Interoperability — The ability of systems to exchange data with unambiguous, shared meaning. Achieved through use of standard terminologies such as SNOMED CT, LOINC, and ICD.

Technical Interoperability — The ability of systems to communicate through agreed protocols and data formats. FHIR is the primary technical interoperability standard in modern health systems.

Interoperability Layer / Enterprise Service Bus / Message Routing — The middleware layer that routes and mediates data exchange between health systems. WHO DHI code 4.4.3. Equivalent to HIE platform function.

Standards-compliant Interoperability — Data exchange using recognised standards such as FHIR, IHE profiles, and WHO CDISAH classifications. WHO DHI code 4.4.2.

ETL — Extract, Transform, Load. Process for moving and converting data from source systems to data warehouses or repositories.

---

## SECTION 4 — Registries and Directories

Facility Registry / Health Facility Registry — A central authority that uniquely identifies all places where health services are administered within a country. WHO code C4. Contains unique IDs, locations, and service information for all health facilities.

Health Worker Registry / Provider Registry — Central authority maintaining unique identities of healthcare providers within a country. WHO code C5.

Terminology Service / Terminology Management Service / Terminology Coding and Mapping Tool — A central authority maintaining a terminology set mapped to international standards including ICD, LOINC, SNOMED. WHO code C11.

Immunisation Information System / Electronic Immunisation Registry / Vaccination Records — Confidential, population-based, computerised databases recording all immunisation doses administered. WHO code C7.

CRVS — Civil Registration and Vital Statistics. Digital systems registering all births and deaths, issuing certificates, and compiling vital statistics. WHO code C2 and DHI 3.4.

---

## SECTION 5 — Clinical and Point-of-Service Systems

PHR — Personal Health Record. A record of an individual's health information in a structured digital format over which the person has agency. Equivalent to patient portals. WHO code A7.

LIMS / Laboratory Information Management System — Systems supporting the process from patient sample to patient result. WHO code A6. Functional areas: lab requests, sample tracking, results reporting.

PACS — Picture Archiving and Communication System. Medical imaging storage and retrieval system. WHO code A4.

Telehealth / Telemedicine / Virtual Health and Care / Teleconsultation — Provision of healthcare services at a distance. WHO code A9. Includes synchronous (real-time) and asynchronous (store and forward) modalities.

Store and Forward / Asynchronous Telemedicine — Transmission of medical data such as images, notes, and videos to a healthcare provider for review without real-time interaction. WHO DHI 2.4.3.

CPOE — Computerized Provider Order Entry. A system allowing healthcare providers to enter medication orders and other instructions electronically. Related to prescription and medication management, WHO DHI 2.9.

Clinical Decision Support / CDS — Computer-based tools combining medical information databases and algorithms with patient-specific data to provide recommendations for diagnosis, prognosis, and treatment. WHO code A3.

---

## SECTION 6 — Health System Administration Systems

HMIS / Health Management Information System — Stores routinely collected aggregate healthcare data. DHIS2 is the leading open source HMIS platform used across low and middle income countries. WHO code D6.

LMIS / Logistics Management Information System / Supply Chain Management System — Systems storing and aggregating routine supply chain data. WHO code B6. Functional areas: stock forecasting, cold chain monitoring, inventory management.

IAM / Identity and Access Management — Digital approaches to managing authentication and authorisation. Controls who can access which data resources. WHO DHI 4.5.1.

EMIS — Environmental Management Information Systems. Systems for obtaining, processing, and making available environmental information relevant to health. WHO code D4.

GIS / Geographic Information System — Computer system that analyses and displays geographically referenced information. Used to map health facilities, events, and populations. WHO code D5.

ADT — Admissions-Discharge-Transfer. Core functional area of patient administration systems managing patient flow through health facilities.

---

## SECTION 7 — Data and Governance

Data Governance — Digital approaches supporting the maintenance of integrity and security of data to enable secondary use of health data. WHO DHI 4.5.

Data Privacy Protection — Securing and classifying sensitive health data, including redaction, data minimisation, and consent management. WHO DHI 4.5.2.

Consent Management / Digital Consent / Electronic Informed Consent — Digital approaches to facilitate and manage the provision and withdrawal of consent by individuals to enable healthcare providers to access or share health records. WHO DHI 1.8 and 4.5.3.

Data Warehouse / Repository / National Data Repository — An enterprise system used for analysis and reporting of structured and semi-structured data from multiple sources. WHO code D3. Functional areas: ETL, data consolidation, data cleaning, reporting.

---

## SECTION 8 — Reference Frameworks

OpenHIE Architecture — Defines a health information architecture using a set of interoperable components: client registry, facility registry, health worker registry, shared health record, terminology service, and interoperability layer. Widely adopted reference architecture for national-scale health information exchange.

ISO/TR 14639 — Health informatics capacity-based eHealth architecture roadmap. Defines technical and governance requirements for national eHealth architectures.

ISO/TR 18307 — Health informatics interoperability and compatibility in messaging and communication standards.

GDPR — General Data Protection Regulation. European data protection framework referenced as a model for consent management and data privacy in health systems globally.

WHO Digital Health Atlas / DHA — Online global repository where implementers register digital health activities. Uses CDISAH taxonomy for classification.

DIIG — Digital Implementation Investment Guide. WHO companion document to CDISAH for planning and implementing digital health interventions.

---

## SECTION 9 — Quick Acronym Reference

ADR — Adverse Drug Reaction
ADT — Admissions-Discharge-Transfer
AI — Artificial Intelligence
CDHI — Classification of Digital Health Interventions (v1.0)
CDISAH — Classification of Digital Interventions, Services and Applications in Health
CDS — Clinical Decision Support
CME — Continuing Medical Education
COBIT — Control Objectives for Information and Related Technologies
CPOE — Computerized Provider Order Entry
CPD — Continuing Professional Development
CRVS — Civil Registration and Vital Statistics
CTMS — Clinical Trial Management Software
DHA — WHO Digital Health Atlas
DHI — Digital Health Intervention (also: Department of Digital Health and Innovation at WHO)
DIIG — Digital Implementation Investment Guide
DOTS — Directly Observed Treatment Short-course
DPI — Digital Public Infrastructure
DPI-H — Digital Public Infrastructure for Health
eHealth — Electronic Health
EHR — Electronic Health Record
EMR — Electronic Medical Record
EMIS — Environmental Management Information Systems
ETL — Extract Transform Load
FHIR — Fast Healthcare Interoperability Resources (HL7 standard)
GIS — Geographic Information Systems
GDPR — General Data Protection Regulation
GPS — Global Positioning System
HIE — Health Information Exchange
HIS — Health Information System
HL7 — Health Level Seven
HMIS — Health Management Information Systems
HSC — Health System Challenge
IAM — Identity and Access Management
ICD — International Classification of Diseases
ICT — Information and Communications Technology
ICPC2 — International Classification of Primary Care version 2
IG — Implementation Guide (FHIR)
ILR — Interoperability Layer Registry (also used for Client Registry in some contexts)
ISO — International Standards Organization
LIMS — Laboratory Information Management System
LMIS — Logistics Management Information Systems
LOINC — Logical Observation Identifiers Names and Codes
mHealth — Mobile Health
MPI — Master Patient Index
ODK — OpenDataKit
OpenHIE — Open Health Information Exchange
PACS — Picture Archiving and Communication System
PHR — Personal Health Record
SHR — Shared Health Record
SMS — Short Message Service
SNOMED CT — Systematized Nomenclature of Medicine Clinical Terms
USSD — Unstructured Supplementary Service Data
XML — Extensible Markup Language
