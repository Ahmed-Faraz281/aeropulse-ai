import { apiClient } from './api';
import type { WhatIfSimulationRequest, WhatIfSimulationResponse } from '../types/whatIf';

export const simulateWhatIf = async (
  request: WhatIfSimulationRequest
): Promise<WhatIfSimulationResponse> => {
  const response = await apiClient.post<WhatIfSimulationResponse>(
    '/what-if/simulate',
    request
  );
  return response.data;
};
