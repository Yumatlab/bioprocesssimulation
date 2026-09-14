% SELECT query function
function T = fetchpy(dbpath, sqlquery)
% call function from python
py_list = py.sqlite_query.execute_sql_query(dbpath, sqlquery);
T = table(py_list);
end