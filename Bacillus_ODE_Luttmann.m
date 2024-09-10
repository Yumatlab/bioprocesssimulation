function [dy] = Bacillus_ODE_Luttmann(qXpX,Din,cS1R1,qS1pX,cS2R1,qS2pX,CPR1tot,qPpX,MP,cOT1,cOT2,cOR1,OTR,OUR,cOL100,TMpO2,DT1,CAcT1tot,qAcpX,MAc,DT2,CAlT2tot,qAlpX,AlTR,MAl,DR1,CCR1tot,CCT1tot,CCT2tot,CTR,CER,MCO2,pHL,TMpH,TMxO2,xOG,TMxCO2,xCG,lamdaF,qhpX,lamdaAF,AAFin,tauD,DD,thetaTc,tauDL,thetaU,tauDU,tauL,tauLD,tauLU,QdotM,QdotSt,CL,t,y)
% ADD HARVEST TO BALANCE LATER

% Cell concentration balance
dy(1) = (qXpX-Din)*y(1);

% Glucose concentration balance
dy(2) = DR1*cS1R1-Din*y(2)-qS1pX*y(1);

% Glycerol concentration balance
dy(3) = DR1*cS2R1-Din*y(3)-qS2pX*y(1);

% Product concentration balance
dy(4) = DR1*CPR1tot-Din*y(4)+qPpX*y(1)/MP;

% O2 concentration balance
dy(5) = DR1*cOR1+DT1*cOT1+DT2*cOT2-Din*y(5)+OTR-OUR;
% #cOL := DR * cOR + DT1 * cOT1 + DT2 * cOT2 - Din * cOL + OTR - OUR;
% pO2 balance
dy(6) = ((y(5)/cOL100)*100-y(6))/TMpO2;
% #pO2 := (cOL / cOL100 * 100 - pO2) / TMpO2;
% Buffer acid balance [mol/(l*h)]
dy(7) = -Din*y(7);

% Buffer base balance [mol/(l*h)]
dy(8) = -Din*y(8);

% Titration acid balance [mol/(l*h)]
dy(9) = DT1*CAcT1tot-Din*y(9)-qAcpX*y(1)/MAc;

% Ammonia balance [mol/(l*h)]
dy(10) = DT2*CAlT2tot-Din*y(10)-(qAlpX*y(1)+AlTR)/MAl;

% Dissolved CO2 balance [mol/(l*h)]
dy(11) = DR1*CCR1tot+DT1*CCT1tot+DT2*CCT2tot-Din*y(11)+(CTR+CER)/MCO2;

% pH-calculation with measurement dynamic [-]
dy(12) = (pHL-y(12))/TMpH;

% O2-mole fraction in offgas with measurement dynamic [-]
dy(13) = (xOG*100-y(13))/TMxO2;

% CO2-mole fraction in offgas with measurement dynamic [-]
dy(14) = (xCG*100-y(14))/TMxCO2;

% Relative foam height [1/h]
dy(15) = lamdaF*y(15)+qhpX*y(1);

% Anti foam activity [1/h] 
dy(16) = lamdaAF*y(16)+AAFin;

% Temperature in double jacket [°C/h]
dy(17) = -y(17)/tauD+DD*thetaTc+y(18)/tauDL+thetaU/tauDU;

% Temperature in liquid phase of reactor [°C/h]
dy(18) = -y(18)/tauL+y(17)/tauLD+thetaU/tauLU+(QdotM+QdotSt)/CL;

dy = dy';
end