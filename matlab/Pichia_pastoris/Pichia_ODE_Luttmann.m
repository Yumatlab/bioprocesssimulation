function [dy] = Pichia_ODE_Luttmann(qXpX,Din,cS1R1,qS1pX,cS2R1,qS2pX,cS1R2,cS2R2,cP1R1,cP1R2,qP1pX,kP1alpha,cOT1,cOT2,cOR1,cOR2,OTR,OUR,cOL100,TMpO2,DT1,CAcT1tot,qAcpX,MAc,DT2,CAlT2tot,qAlpX,AlTR,MAl,DR1,DR2,CCRtot,CCT1tot,CCT2tot,CTR,CER,MCO2,pHL,TMpH,TMxO2,xOG,TMxCO2,xCG,lamdaF,qhpX,lamdaAF,AAFin,tauD,DD,thetaTc,tauDL,thetaU,tauDU,tauL,tauLD,tauLU,QdotM,QdotSt,CL,t,y)
% ADD HARVEST TO BALANCE LATER 
% %(app.v.qXpX(end),Din,app.p.cS1R1,qS1pX,app.p.cS2R1,qS2pX,app.p.cP1R1,app.p.cP1R2,app.v.qP1pX(end),app.p.cOT1,app.p.cOT2,app.p.cOR1,app.p.cOR2,app.v.OTR(end),app.v.OUR(end),app.cOL100,app.p.TMpO2,DT1,app.p.CAcT1tot,qAcpX,app.p.MAc,DT2,app.p.CAlT2tot,qAlpX,AlTR,app.p.MAl,DR1,app.p.CCRtot,app.p.CCT1tot,app.p.CCT2tot,app.v.CTR(end),CER,app.p.MCO2,app.v.pHL(end),app.p.TMpH,app.p.TMxO2,app.v.xOG(end),app.p.TMxCO2,app.v.xCG(end),lambdaF,app.p.qhpX,lambdaAF,AAFin,app.tauD,app.DD,app.thetaTc,app.tauDL,app.p.thetaU,app.tauDU,tauL,tauLD,tauLU,QdotM,QdotSt,CL,t,y);

% Cell concentration balance
dy(1) = (qXpX-Din)*y(1);

% Glycerol concentration balance
dy(2) = DR1*cS1R1+DR2*cS1R2-Din*y(2)-qS1pX*y(1);

% Methanol concentration balance
dy(3) = DR1*cS2R1+DR2*cS2R2-Din*y(3)-qS2pX*y(1);

% Product concentration in cell balance
dy(4) = qP1pX*y(1)-Din*y(4)-kP1alpha*y(4);

% Product concentration in liquid balance
dy(5) = DR1*cP1R1+DR2*cP1R2+kP1alpha*y(4)-Din*y(5);

% O2 concentration balance
dy(6) = DR1*cOR1+DR2*cOR2+DT1*cOT1+DT2*cOT2-Din*y(6)+OTR-OUR;

% pO2 balance
dy(7) = ((y(6)/cOL100)*100-y(7))/TMpO2;

% Buffer acid balance [mol/(l*h)]
dy(8) = -Din*y(8);

% Buffer base balance [mol/(l*h)]
dy(9) = -Din*y(9);

% Titration acid balance [mol/(l*h)]
dy(10) = DT1*CAcT1tot-Din*y(10)-qAcpX*y(1)/MAc;

% Ammonia balance [mol/(l*h)]
dy(11) = DT2*CAlT2tot-Din*y(11)-(qAlpX*y(1)+AlTR)/MAl;

% Dissolved CO2 balance [mol/(l*h)]
dy(12) = DR1*CCRtot+DT1*CCT1tot+DT2*CCT2tot-Din*y(12)+(CTR+CER)/MCO2; % Adjust here CCR1tot and CCR2tot

% pH-calculation with measurement dynamic [-]
dy(13) = (pHL-y(13))/TMpH;

% O2-mole fraction in offgas with measurement dynamic [-]
dy(14) = (xOG*100-y(14))/TMxO2;

% CO2-mole fraction in offgas with measurement dynamic [-]
dy(15) = (xCG*100-y(15))/TMxCO2;

% Relative foam height [1/h]
dy(16) = lamdaF*y(16)+qhpX*y(1);

% Anti foam activity [1/h] 
dy(17) = lamdaAF*y(17)+AAFin;

% Temperature in double jacket [°C/h]
dy(18) = -y(18)/tauD+DD*thetaTc+y(19)/tauDL+thetaU/tauDU;

% Temperature in liquid phase of reactor [°C/h]
dy(19) = -y(19)/tauL+y(18)/tauLD+thetaU/tauLU+(QdotM+QdotSt)/CL;

dy = dy';
end