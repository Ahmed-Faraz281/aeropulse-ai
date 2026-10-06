import React from 'react';
import type { AQIResponse } from '../../types/aqi';
import type { SourceType } from '../../types/air_quality';
import type { DataFreshnessStatus } from '../../types/trust';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import { HeroAQIDisplay } from '../common/HeroAQIDisplay';

interface CurrentAQICardProps {
  aqiData: AQIResponse | null;
  locationName: string;
  sourceType?: SourceType;
  freshnessStatus?: DataFreshnessStatus | string | null;
  freshnessAgeHours?: number | null;
  isLoading: boolean;
}

export const CurrentAQICard: React.FC<CurrentAQICardProps> = ({
  aqiData,
  locationName,
  sourceType,
  freshnessStatus,
  freshnessAgeHours,
  isLoading,
}) => {
  const isAvailable = aqiData && aqiData.status === 'CALCULATED' && aqiData.aqi !== null;
  const categoryStyle = getAQICategoryStyle(aqiData?.category);

  return (
    <HeroAQIDisplay
      aqi={isAvailable ? aqiData.aqi : null}
      category={isAvailable ? categoryStyle.label : null}
      dominantPollutant={isAvailable ? aqiData.dominant_pollutant : null}
      status={aqiData?.status}
      stationName={locationName}
      timestamp={aqiData?.timestamp}
      sourceType={sourceType}
      freshnessStatus={freshnessStatus}
      freshnessAgeHours={freshnessAgeHours}
      isLoading={isLoading}
      className="h-full flex flex-col justify-between"
    />
  );
};

export default CurrentAQICard;
