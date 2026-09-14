%% Batch End pO2 Slope
% Inputs:
% v = variable struct
% p = parameter struct
% t = time array
function flag = BatchEndDetection_pO2Slope(v,deltat,t,idx)
% regression over 1 min
n = 60/deltat-1;
if length(v.pO2) > n
    pO2 = v.pO2(idx-n:idx);
    NSt = v.NSt(idx-n:idx);
else
    pO2 = v.pO2(1:idx);
    NSt = v.NSt(1:idx);
end
t = t(idx-n:idx);
% slope determination based on linar regression
% pO2 slope determination
p_pO2 = polyfit(t,pO2,1);
slope_pO2 = p_pO2(1);

% NSt slope determination
p_NSt = polyfit(t,NSt,1);
slope_NSt = p_NSt(1);

% pO2 condition check
if slope_pO2 > 1000
    flag_pO2 = true; 
else
    flag_pO2 = false;
end

% NSt condition check
if slope_NSt < -1000
    flag_NSt = true;
else 
    flag_NSt = false;
end
fprintf("pO2 = %g, NSt = %g\n", slope_pO2, slope_NSt)
% Summary
if flag_pO2 && flag_NSt
    %flag = true;
    disp("Condition true!")
else
    flag = false;
end
end