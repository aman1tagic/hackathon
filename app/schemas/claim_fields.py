from typing import Literal

ClaimType = Literal["cashless", "reimbursement"]

DOCUMENT_CLASSIFICATION_TYPES = [
    "Aadhar Card",
    "Bills",
    "CKYC_CKYC Form",
    "CKYC_ID Proof",
    "Claim Form",
    "Consultation Papers",
    "Discharge Card",
    "Email",
    "FIR_MLC copy",
    "Final Bill",
    "ICP",
    "ID Proof",
    "Medical Reports",
    "Member Health Card",
    "NEFT_Cancelled Cheque_other NEFT document",
    "Other",
    "PAN Card",
    "Pharmacy Bill",
    "Pre Auth Form",
]


CASHLESS_FIELD_CATALOG = [
    {
        "path": "i3_case_id",
        "context": "Internal I3 case identifier. Extract only if explicitly available in source/system metadata; do not infer.",
    },
    {
        "path": "caseId",
        "context": "Unique case identifier for the cashless claim. Extract only case-level claim identifier.",
    },
    {
        "path": "memberDetails.isContactDetailsDifferent",
        "context": "Whether member/patient contact details differ from registered details. Usually Yes/No.",
    },
    {
        "path": "memberDetails.isAlternateAddressDifferent",
        "context": "Whether alternate/current address differs from registered member address. Usually Yes/No.",
    },
    {
        "path": "patientDetailsFromHospital.modality",
        "context": "Treatment modality such as Allopathic, Ayurvedic, Homeopathic.",
    },
    {
        "path": "patientDetailsFromHospital.patientHospitalDetails[].natureOfIllness",
        "context": "Symptoms, illness, disease, injury, or complaints for hospitalization/treatment.",
    },
    {
        "path": "patientDetailsFromHospital.patientHospitalDetails[].revelentCriticalFindings",
        "context": "Relevant clinical findings such as pulse, BP, temperature, examination findings, abnormal observations.",
    },
    {
        "path": "patientDetailsFromHospital.patientHospitalDetails[].durationOfPresentAlignment",
        "context": "Duration of present ailment/illness before admission or consultation.",
    },
    {
        "path": "patientDetailsFromHospital.patientHospitalDetails[].dateOfFirstConsultation",
        "context": "Date of first consultation for current illness. Prefer YYYY-MM-DD.",
    },
    {
        "path": "patientDetailsFromHospital.patientHospitalDetails[].pastHistoryOfPresentAlignment",
        "context": "Past history related to present ailment, not unrelated chronic illnesses unless source links them.",
    },
    {
        "path": "patientDetailsFromHospital.accident",
        "context": "Whether hospitalization/treatment is accident-related. Usually Yes/No.",
    },
    {
        "path": "patientDetailsFromHospital.accidentDetails.reportToPolice",
        "context": "Whether the accident was reported to police. Extract explicitly stated Yes/No/equivalent.",
    },
    {
        "path": "patientDetailsFromHospital.accidentDetails.injuryDiseaseCausedToAlcoholSubstanceAbuseConsumption",
        "context": "Whether injury/disease was caused by or associated with alcohol, drugs, or substance abuse.",
    },
    {
        "path": "patientDetailsFromHospital.maternity",
        "context": "Whether hospitalization/claim is maternity-related. Usually Yes/No.",
    },
    {
        "path": "patientAdmissionDetails.emergencyOrPlannedHospitalizationEvent",
        "context": "Nature of hospitalization/admission: Emergency or Planned/Elective.",
    },
    {
        "path": "patientAdmissionDetails.expectedNoOfDaysOrStayInHospital",
        "context": "Expected total number of days in hospital. Do not confuse with ICU days.",
    },
    {
        "path": "patientAdmissionDetails.expectedDateOfDischarge",
        "context": "Expected/proposed discharge date. Prefer YYYY-MM-DD.",
    },
    {
        "path": "patientAdmissionDetails.daysInICU",
        "context": "Expected/reported ICU days. Do not use total hospitalization duration.",
    },
    {
        "path": "patientAdmissionDetails.mandatoryPastHistoryOfChronicIllness[].diseaseName",
        "context": "Name of chronic disease/comorbidity being checked, such as Diabetes, Hypertension, Heart Disease.",
    },
    {
        "path": "patientAdmissionDetails.mandatoryPastHistoryOfChronicIllness[].remarks",
        "context": "Reported status, presence/absence, duration, or remarks for that chronic disease.",
    },
    {
        "path": "patientAdmissionDetails.roomType",
        "context": "Admission-level room category requested/occupied/expected, such as Single Room, General Ward, ICU.",
    },
    {
        "path": "patientAdmissionDetails.expectedCostOfHospitalization",
        "context": "Total estimated/expected hospitalization cost, not individual invoice/service amounts.",
    },
    {
        "path": "billingDetails.isFinalApproval",
        "context": "Whether billing/claim information corresponds to final approval/final billing.",
    },
    {
        "path": "billingDetails.billingType",
        "context": "Type/structure of billing submitted by hospital, for example Itemwise.",
    },
    {
        "path": "invoiceDetails[].invoiceNumber",
        "context": "Invoice, bill, or receipt number. Do not use claim/case identifiers.",
    },
    {
        "path": "invoiceDetails[].invoiceDate",
        "context": "Date of corresponding invoice/bill. Prefer YYYY-MM-DD.",
    },
    {
        "path": "invoiceDetails[].discount",
        "context": "Invoice-level discount amount, not line-item inferred discount.",
    },
    {
        "path": "invoiceDetails[].return",
        "context": "Invoice-level return/refund/reversal amount.",
    },
    {
        "path": "invoiceDetails[].services[].itemDescription",
        "context": "Billed service/procedure/investigation/medicine/consumable/room/doctor charge description.",
    },
    {
        "path": "invoiceDetails[].services[].categoryLevel4",
        "context": "Detailed billing category assigned to service line.",
    },
    {
        "path": "invoiceDetails[].services[].categoryLevel1",
        "context": "High-level billing category such as Investigation Charges, Room & Nursing, ICU, Professional fees.",
    },
    {
        "path": "invoiceDetails[].services[].roomType",
        "context": "Room type/category for this service line only when explicitly available.",
    },
    {
        "path": "invoiceDetails[].services[].units",
        "context": "Quantity/units for billed item. Preserve negative quantities.",
    },
    {
        "path": "invoiceDetails[].services[].grossAmount",
        "context": "Gross amount for service line. Preserve negative amounts.",
    },
    {
        "path": "invoiceDetails[].services[].isNonPayable",
        "context": "Whether service line is non-payable/non-admissible. Usually true/false.",
    },
    {
        "path": "invoiceDetails[].services[].nonPayableReason",
        "context": "Reason service/item is non-payable when explicitly available.",
    },
    {
        "path": "dpcDetails.diagnosis[].diagnosisName",
        "context": "Diagnosed disease, disorder, injury, or medical condition.",
    },
    {
        "path": "dpcDetails.diagnosis[].icdCode",
        "context": "ICD diagnosis code exactly when available; do not generate.",
    },
    {
        "path": "dpcDetails.diagnosis[].shortDescription",
        "context": "Short clinical or ICD description.",
    },
    {
        "path": "dpcDetails.diagnosis[].longDescription",
        "context": "Detailed clinical or ICD description.",
    },
    {
        "path": "dpcDetails.diagnosis[].lineOfTreatment",
        "context": "Broad treatment approach, for example Medical or Surgical.",
    },
    {
        "path": "dpcDetails.diagnosis[].routeOfDrugAdministration",
        "context": "Drug administration route such as Oral, IV, IM, All.",
    },
    {
        "path": "retryCount",
        "context": "Operational retry count. Do not infer from medical documents.",
    },
]


REIMBURSEMENT_FIELD_CATALOG = [
    {"path": "i3_case_id", "context": "Internal I3 case identifier. Extract only if explicitly available."},
    {"path": "caseId", "context": "Unique reimbursement claim identifier."},
    {
        "path": "memberDetails.claimedAmount",
        "context": "Total reimbursement amount claimed by insured. Do not confuse with invoice totals/approved amount.",
    },
    {
        "path": "memberDetails.isContactDetailsDifferent",
        "context": "Whether claimant contact details differ from registered details.",
    },
    {
        "path": "memberDetails.alternateMobileNumberOne",
        "context": "Alternate mobile number of claimant.",
    },
    {
        "path": "memberDetails.isAlternateAddressDifferent",
        "context": "Whether claimant alternate address differs from registered address.",
    },
    {
        "path": "insuranceHistoryDetails.isCurrentlyCoveredByOtherInsurance",
        "context": "Whether insured currently has another active health insurance policy.",
    },
    {
        "path": "insuranceHistoryDetails.ishospitalizedLastFourYears",
        "context": "Whether insured was hospitalized during previous four years.",
    },
    {
        "path": "insuranceHistoryDetails.isPreviouslyCoveredByOtherInsurance",
        "context": "Whether insured was previously covered under another insurance policy.",
    },
    {"path": "bankDetails.panCard", "context": "PAN of claimant."},
    {"path": "bankDetails.accountNumber", "context": "Bank account number for reimbursement credit."},
    {"path": "bankDetails.ifscCode", "context": "IFSC code of beneficiary bank."},
    {
        "path": "bankDetails.chequeDDPayableDetails",
        "context": "Document submitted for bank verification such as cancelled cheque, passbook, bank statement.",
    },
    {"path": "invoiceDetails[].invoiceNumber", "context": "Invoice or bill number."},
    {"path": "invoiceDetails[].invoiceDate", "context": "Date of invoice. Prefer YYYY-MM-DD."},
    {"path": "invoiceDetails[].discount", "context": "Invoice-level discount amount."},
    {"path": "invoiceDetails[].return", "context": "Invoice-level return/refund/reversal amount."},
    {
        "path": "invoiceDetails[].services[].itemDescription",
        "context": "Name/description of billed service, medicine, consumable, investigation, procedure, room charge, fee.",
    },
    {
        "path": "invoiceDetails[].services[].categoryLevel4",
        "context": "Detailed billing category assigned to service.",
    },
    {
        "path": "invoiceDetails[].services[].categoryLevel1",
        "context": "Top-level billing category such as Investigation, OT, Medicine & Consumables, Room & Nursing, ICU.",
    },
    {
        "path": "invoiceDetails[].services[].roomType",
        "context": "Room category associated with billing line when explicitly available.",
    },
    {"path": "invoiceDetails[].services[].units", "context": "Quantity billed. Preserve negative values."},
    {
        "path": "invoiceDetails[].services[].grossAmount",
        "context": "Gross billed amount for service line. Preserve negative values.",
    },
    {
        "path": "invoiceDetails[].services[].isNonPayable",
        "context": "Whether service line is marked non-payable.",
    },
    {
        "path": "invoiceDetails[].services[].nonPayableReason",
        "context": "Reason for non-payability when explicitly mentioned.",
    },
    {"path": "dpcDetails.modality", "context": "Treatment modality such as Allopathic."},
    {
        "path": "dpcDetails.ailment",
        "context": "Overall illness/medical condition for hospitalization.",
    },
    {"path": "dpcDetails.dischargeICDCode", "context": "Primary discharge ICD diagnosis code."},
    {
        "path": "dpcDetails.dischargeShortDescription",
        "context": "Short description of discharge ICD diagnosis.",
    },
    {
        "path": "dpcDetails.dischargeLongDescription",
        "context": "Detailed description of discharge ICD diagnosis.",
    },
    {"path": "dpcDetails.diagnosis[].diagnosisName", "context": "Diagnosis or disease name."},
    {"path": "dpcDetails.diagnosis[].icdCode", "context": "ICD diagnosis code for diagnosis."},
    {"path": "dpcDetails.diagnosis[].shortDescription", "context": "Short ICD description."},
    {"path": "dpcDetails.diagnosis[].longDescription", "context": "Detailed ICD description."},
    {
        "path": "dpcDetails.diagnosis[].nameOfSurgery",
        "context": "Surgical procedure performed for diagnosis, if applicable.",
    },
    {
        "path": "dpcDetails.diagnosis[].icd10PCSCode",
        "context": "ICD-10-PCS procedure code for surgery.",
    },
    {
        "path": "dpcDetails.diagnosis[].lineOfTreatment",
        "context": "Treatment approach such as Medical or Surgical.",
    },
    {
        "path": "dpcDetails.diagnosis[].routeOfDrugAdministration",
        "context": "Drug administration route such as Oral, IV, IM, All.",
    },
    {"path": "hospitalisationDetails.dateOfDischarge", "context": "Actual date of discharge."},
    {
        "path": "hospitalisationDetails.hospitalizationDueTo",
        "context": "Reason for hospitalization such as Illness, Accident, or Maternity.",
    },
    {
        "path": "hospitalisationDetails.injuryDetails.roadTrafficAccidentDetails.isMedicaLegal",
        "context": "Whether case is medico-legal.",
    },
    {
        "path": "hospitalisationDetails.injuryDetails.roadTrafficAccidentDetails.reportedToPolice",
        "context": "Whether accident was reported to police.",
    },
    {
        "path": "hospitalisationDetails.injuryDetails.roadTrafficAccidentDetails.mlcReportAndPoliceFIRAttached",
        "context": "Whether MLC report and police FIR are attached.",
    },
    {
        "path": "hospitalisationDetails.statusOfDischarge",
        "context": "Patient discharge status.",
    },
    {
        "path": "hospitalisationDetails.typeOfAdmission",
        "context": "Admission type such as Emergency or Planned.",
    },
    {
        "path": "hospitalisationDetails.roomCategoryOccupied",
        "context": "Actual room category occupied during hospitalization.",
    },
    {
        "path": "retryCount",
        "context": "Internal processing retry count. Operational metadata, not medical information.",
    },
]


def get_field_catalog(claim_type: ClaimType) -> list[dict[str, str]]:
    if claim_type == "cashless":
        return CASHLESS_FIELD_CATALOG
    return REIMBURSEMENT_FIELD_CATALOG

