import { apiClient } from './api';
import type { ReportGenerateRequest, ReportPreviewResponse } from '../types/report';

export const previewReport = async (
  request: ReportGenerateRequest
): Promise<ReportPreviewResponse> => {
  const response = await apiClient.post<ReportPreviewResponse>('/reports/preview', request);
  return response.data;
};

export const downloadReportPdf = async (
  request: ReportGenerateRequest
): Promise<void> => {
  const response = await apiClient.post('/reports/generate', request, {
    responseType: 'blob',
  });

  let filename = `AeroPulse_Report_${request.report_type}_${new Date().toISOString().slice(0, 10)}.pdf`;
  const disposition = response.headers['content-disposition'];
  if (disposition && disposition.includes('filename=')) {
    const match = disposition.match(/filename="?([^";]+)"?/);
    if (match && match[1]) {
      filename = match[1];
    }
  }

  const blob = new Blob([response.data], { type: 'application/pdf' });
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(downloadUrl);
};
