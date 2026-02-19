proc sql;
    CREATE TABLE curcdd_counts AS
    SELECT curcdd, count(*) AS n
    FROM comp.g_secd
    GROUP BY curcdd
    ORDER BY n DESC;
quit;

proc print data=curcdd_counts;
run;
