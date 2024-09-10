% INSERT, UPDATE, DELETE query function
function execpy(dbpath, sqlquery)
py.sqlite_modify.execute_sql_modify(dbpath, sqlquery);
end
