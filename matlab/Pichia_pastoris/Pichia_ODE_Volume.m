function [dyV] = Pichia_ODE_Volume(FR1,FR2,FH,FT1,FT2,t,yV)

% Liquid volume balance [l/h]
dyV(1) = FR1+FR2+FT1+FT2-FH;

% Substrate reservoir 1 balance [l/h]
dyV(2) = -FR1;

% Substrate reservoir 2 balance [l/h]
dyV(3) = -FR2;

% pH-base reservoir balance [l/h]
dyV(4) = -FT2;

% pH-acid reservoir balance [l/h]
dyV(5) = -FT1;

dyV = dyV';
end