function [dyV] = Bacillus_ODE_Volume(FR1,FH,FT1,FT2,t,yV)

% Liquid volume balance [l/h]
dyV(1) = FR1+FT1+FT2-FH;

% Substrate reservoir balance [l/h]
dyV(2) = -FR1;

% pH-base reservoir balance [l/h]
dyV(3) = -FT2;

% pH-acid reservoir balance [l/h]
dyV(4) = -FT1;

dyV = dyV';
end