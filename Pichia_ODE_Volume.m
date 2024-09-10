function [dyV] = ODE_Volume_New(FR1,FR2,FR3,FH,FT1,FT2,t,yV)

% Liquid volume balance [l/h]
dyV(1) = FR1+FR2+FR3+FT1+FT2-FH;

% Substrate reservoir 1 balance [l/h]
dyV(2) = -FR1;

% Substrate reservoir 2 balance [l/h]
dyV(3) = -FR2;

% Substrate reservoir 3 balance [l/h]
dyV(4) = -FR3;

% pH-base reservoir balance [l/h]
dyV(5) = -FT2;

% pH-acid reservoir balance [l/h]
dyV(6) = -FT1;

dyV = dyV';
end